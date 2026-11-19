import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { SignIn } from '@/features/auth/SignIn'
import { AuthGate } from './auth'
import { Shell } from './Shell'

const AssistantPage = lazy(() => import('@/features/assistant/Assistant').then((module) => ({ default: module.AssistantPage })))
const Insights = lazy(() => import('@/features/insights/Insights').then((module) => ({ default: module.Insights })))
const Finance = lazy(() => import('@/features/finance/Finance').then((module) => ({ default: module.Finance })))
const Tasks = lazy(() => import('@/features/tasks/Tasks').then((module) => ({ default: module.Tasks })))
const Customers = lazy(() => import('@/features/customers/Customers').then((module) => ({ default: module.Customers })))
const Enquiries = lazy(() => import('@/features/enquiries/Enquiries').then((module) => ({ default: module.Enquiries })))
const Fulfilment = lazy(() => import('@/features/fulfilment/Fulfilment').then((module) => ({ default: module.Fulfilment })))
const Home = lazy(() => import('@/features/home/Home').then((module) => ({ default: module.Home })))
const Integrations = lazy(() => import('@/features/integrations/Integrations').then((module) => ({ default: module.Integrations })))
const Orders = lazy(() => import('@/features/orders/Orders').then((module) => ({ default: module.Orders })))
const Products = lazy(() => import('@/features/products/Products').then((module) => ({ default: module.Products })))
const PurchaseOrders = lazy(() => import('@/features/purchasing/PurchaseOrders').then((module) => ({ default: module.PurchaseOrders })))
const Receipts = lazy(() => import('@/features/receipts/Receipts').then((module) => ({ default: module.Receipts })))
const PriceLists = lazy(() => import('@/features/pricing/PriceLists').then((module) => ({ default: module.PriceLists })))
const StockCount = lazy(() => import('@/features/stock/StockCount').then((module) => ({ default: module.StockCount })))
const StockIn = lazy(() => import('@/features/stockin/StockIn').then((module) => ({ default: module.StockIn })))
const Suppliers = lazy(() => import('@/features/suppliers/Suppliers').then((module) => ({ default: module.Suppliers })))

export function App() {
  return (
    <AuthGate signIn={<SignIn />}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Home />} />
          <Route path="assistant/:id?" element={<AssistantPage />} />
          <Route path="insights" element={<Insights />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="finance" element={<Finance />} />
          <Route path="fulfilment" element={<Fulfilment />} />
          <Route path="enquiries/:id?" element={<Enquiries />} />
          <Route path="orders/:id?" element={<Orders />} />
          <Route path="customers/:id?" element={<Customers />} />
          <Route path="purchase-orders/:id?" element={<PurchaseOrders />} />
          <Route path="receipts/:id?" element={<Receipts />} />
          <Route path="suppliers/:id?" element={<Suppliers />} />
          <Route path="products/:id?" element={<Products />} />
          <Route path="stock-in" element={<StockIn />} />
          <Route path="stock-count" element={<StockCount />} />
          <Route path="price-lists" element={<PriceLists />} />
          <Route path="integrations/:section?" element={<Integrations />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AuthGate>
  )
}
