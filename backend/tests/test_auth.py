"""Signing in: every route is guarded except sign-in, health and Meta's webhook."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import auth as auth_service


@pytest.fixture()
def admin(db):
    return auth_service.create_user(db, "Admin", "correct-horse-battery", is_admin=True)


def sign_in(client, password="correct-horse-battery", username="admin"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_without_signing_in_the_data_is_closed(anonymous_client, admin):
    for path in ("/api/products", "/api/customers", "/api/orders", "/api/integrations",
                 "/api/inventory/summary", "/api/auth/me"):
        response = anonymous_client.get(path)
        assert response.status_code == 401, path
    # Open on purpose: the load balancer's check, and Meta's webhook check.
    assert anonymous_client.get("/api/health").status_code in (200, 503)
    assert anonymous_client.get("/api/integrations/whatsapp/webhook").status_code == 403


def test_signing_in_opens_everything_and_signing_out_closes_it(anonymous_client, admin):
    response = sign_in(anonymous_client)
    assert response.status_code == 200 and response.json() == {"username": "admin", "is_admin": True}
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert anonymous_client.get("/api/products").status_code == 200
    assert anonymous_client.get("/api/auth/me").json()["username"] == "admin"

    assert anonymous_client.post("/api/auth/logout").status_code == 204
    assert anonymous_client.get("/api/products").status_code == 401


def test_a_wrong_password_is_refused_and_repeated_ones_lock_the_name(anonymous_client, admin):
    auth_service._failures.clear()
    assert sign_in(anonymous_client, "nope").status_code == 401
    for _ in range(auth_service.MAX_FAILURES):
        sign_in(anonymous_client, "nope")
    assert sign_in(anonymous_client).status_code == 429  # even the right one, for now
    auth_service._failures.clear()


def test_passwords_are_stored_hashed(db, admin):
    assert "correct-horse" not in admin.password_hash
    assert admin.password_hash.startswith("scrypt$")


def test_a_tampered_or_old_session_is_refused(anonymous_client, admin, db):
    sign_in(anonymous_client)
    token = anonymous_client.cookies.get(auth_service.COOKIE)
    user_id, expires, version, signature = token.split(".")
    forged = "{}.{}.{}.{}".format(user_id, int(expires) + 999999, version, signature)
    anonymous_client.cookies.set(auth_service.COOKIE, forged)
    assert anonymous_client.get("/api/products").status_code == 401


def test_changing_the_password_signs_out_other_sessions(anonymous_client, admin, session_factory):
    sign_in(anonymous_client)
    old = anonymous_client.cookies.get(auth_service.COOKIE)
    response = anonymous_client.post("/api/auth/password", json={
        "current_password": "correct-horse-battery", "new_password": "a-new-longer-secret"})
    assert response.status_code == 200
    assert anonymous_client.get("/api/products").status_code == 200  # this session carries on
    anonymous_client.cookies.set(auth_service.COOKIE, old)
    assert anonymous_client.get("/api/products").status_code == 401  # the old one is out
    anonymous_client.cookies.clear()
    assert sign_in(anonymous_client, "a-new-longer-secret").status_code == 200
    short = anonymous_client.post("/api/auth/password", json={
        "current_password": "a-new-longer-secret", "new_password": "short"})
    assert short.status_code == 422


def test_the_first_admin_comes_from_the_environment(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_username", "Owner")
    monkeypatch.setattr(get_settings(), "admin_password", "first-admin-password")
    auth_service.ensure_admin(db)
    user = auth_service.sign_in(db, "owner", "first-admin-password")
    assert user.is_admin
    # Only when nobody exists yet: it never overwrites.
    monkeypatch.setattr(get_settings(), "admin_password", "something-else-entirely")
    auth_service.ensure_admin(db)
    assert auth_service.sign_in(db, "owner", "first-admin-password").username == "owner"
