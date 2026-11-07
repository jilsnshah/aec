import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { ToastProvider } from './components/toast'
import CustomerDetailPage from './pages/CustomerDetail'
import CustomersPage from './pages/Customers'
import DashboardPage from './pages/Dashboard'
import EnquiriesPage from './pages/Enquiries'
import GoodsReceiptsPage from './pages/GoodsReceipts'
import PendingFulfilmentPage from './pages/PendingFulfilment'
import PurchaseOrderDetailPage from './pages/PurchaseOrderDetail'
import PurchaseOrdersPage from './pages/PurchaseOrders'
import SuppliersPage from './pages/Suppliers'
import EnquiryDetailPage from './pages/EnquiryDetail'
import OrderDetailPage from './pages/OrderDetail'
import OrdersPage from './pages/Orders'
import ProductsPage from './pages/Products'
import StockInPage from './pages/StockIn'
import IntegrationsPage from './pages/Integrations'

export default function App() {
  return (
    <ToastProvider>
      <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="customers" element={<CustomersPage />} />
        <Route path="customers/:customerId" element={<CustomerDetailPage />} />
        <Route path="enquiries" element={<EnquiriesPage />} />
        <Route path="enquiries/:enquiryId" element={<EnquiryDetailPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/:orderId" element={<OrderDetailPage />} />
        <Route path="pending-fulfilment" element={<PendingFulfilmentPage />} />
        <Route path="suppliers" element={<SuppliersPage />} />
        <Route path="purchase-orders" element={<PurchaseOrdersPage />} />
        <Route path="purchase-orders/:poId" element={<PurchaseOrderDetailPage />} />
        <Route path="goods-receipts" element={<GoodsReceiptsPage />} />
        <Route path="stock-in" element={<StockInPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
      </Routes>
    </ToastProvider>
  )
}
