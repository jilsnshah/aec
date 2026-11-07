import type { LucideIcon } from 'lucide-react'
import {
  CustomersIcon,
  EnquiryIcon,
  FulfilmentIcon,
  GoodsReceiptIcon,
  IntegrationsIcon,
  OverviewIcon,
  ProductsIcon,
  PurchaseOrderIcon,
  SalesOrderIcon,
  StockInIcon,
  SupplierIcon,
} from './icons'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Exact match only, for the root route. */
  end?: boolean
  /** Extra words the command palette should match. */
  keywords?: string
}

export interface NavSection {
  heading?: string
  items: NavItem[]
}

/** The information architecture: what the business does, in the order it
 *  does it. Selling, buying, then the stock that sits between them. */
export const NAV: NavSection[] = [
  {
    items: [
      { to: '/', label: 'Overview', icon: OverviewIcon, end: true, keywords: 'dashboard home' },
      {
        to: '/pending-fulfilment',
        label: 'Fulfilment',
        icon: FulfilmentIcon,
        keywords: 'pending commitments owed to deliver delivery ready waiting',
      },
    ],
  },
  {
    heading: 'Sales',
    items: [
      { to: '/enquiries', label: 'Enquiries', icon: EnquiryIcon, keywords: 'quote deal discount' },
      { to: '/orders', label: 'Sales Orders', icon: SalesOrderIcon, keywords: 'so order' },
      { to: '/customers', label: 'Customers', icon: CustomersIcon, keywords: 'client buyer' },
    ],
  },
  {
    heading: 'Purchasing',
    items: [
      {
        to: '/purchase-orders',
        label: 'Purchase Orders',
        icon: PurchaseOrderIcon,
        keywords: 'po buy',
      },
      {
        to: '/goods-receipts',
        label: 'Goods Receipts',
        icon: GoodsReceiptIcon,
        keywords: 'gr receive grn arrival',
      },
      { to: '/suppliers', label: 'Suppliers', icon: SupplierIcon, keywords: 'vendor' },
    ],
  },
  {
    heading: 'Inventory',
    items: [
      { to: '/products', label: 'Products', icon: ProductsIcon, keywords: 'sku item stock' },
      { to: '/stock-in', label: 'Stock In', icon: StockInIcon, keywords: 'adhoc receipt grn' },
    ],
  },
  {
    heading: 'Settings',
    items: [
      {
        to: '/integrations',
        label: 'Integrations',
        icon: IntegrationsIcon,
        keywords: 'ai whatsapp email claude webhook imap automation',
      },
    ],
  },
]

export const NAV_ITEMS: NavItem[] = NAV.flatMap((section) => section.items)

/** The label of the section a path belongs to, for the mobile title bar. */
export function titleForPath(pathname: string): string {
  const match = [...NAV_ITEMS]
    .sort((a, b) => b.to.length - a.to.length)
    .find((item) => (item.end ? pathname === item.to : pathname.startsWith(item.to)))
  return match?.label ?? 'AEC'
}
