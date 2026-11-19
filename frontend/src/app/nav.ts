import type { LucideIcon } from 'lucide-react'
import {
  Boxes,
  Building2,
  ClipboardList,
  Home,
  MessageSquareQuote,
  PackageCheck,
  PackageOpen,
  PackagePlus,
  Plug,
  ReceiptText,
  Users,
} from 'lucide-react'

export interface Module {
  to: string
  label: string
  short: string
  icon: LucideIcon
  group: 'main' | 'sales' | 'buying' | 'stock' | 'settings'
  keywords?: string
}

/** The modules, in the order the business works: sell, buy, keep stock. */
export const MODULES: Module[] = [
  { to: '/', label: 'Home', short: 'Home', icon: Home, group: 'main', keywords: 'dashboard overview' },
  { to: '/fulfilment', label: 'Fulfilment', short: 'Fulfil', icon: PackageCheck, group: 'main', keywords: 'deliver ready short on order' },
  { to: '/enquiries', label: 'Enquiries', short: 'Enquiries', icon: MessageSquareQuote, group: 'sales', keywords: 'quote deal' },
  { to: '/orders', label: 'Sales Orders', short: 'Orders', icon: ReceiptText, group: 'sales', keywords: 'so sell' },
  { to: '/customers', label: 'Customers', short: 'Customers', icon: Users, group: 'sales', keywords: 'client buyer' },
  { to: '/purchase-orders', label: 'Purchase Orders', short: 'Purchases', icon: ClipboardList, group: 'buying', keywords: 'po buy' },
  { to: '/receipts', label: 'Goods Receipts', short: 'Receipts', icon: PackageOpen, group: 'buying', keywords: 'grn arrival receive' },
  { to: '/suppliers', label: 'Suppliers', short: 'Suppliers', icon: Building2, group: 'buying', keywords: 'vendor' },
  { to: '/products', label: 'Products', short: 'Products', icon: Boxes, group: 'stock', keywords: 'sku item stock' },
  { to: '/stock-in', label: 'Stock In', short: 'Stock in', icon: PackagePlus, group: 'stock', keywords: 'receipt without po adhoc' },
  { to: '/integrations', label: 'Integrations', short: 'Connect', icon: Plug, group: 'settings', keywords: 'ai whatsapp email tally settings' },
]

export const moduleFor = (pathname: string) =>
  [...MODULES].sort((a, b) => b.to.length - a.to.length).find((module) => (module.to === '/' ? pathname === '/' : pathname.startsWith(module.to))) ?? MODULES[0]
