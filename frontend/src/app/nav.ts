import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  Boxes,
  Building2,
  ClipboardCheck,
  ClipboardList,
  Home,
  ListChecks,
  MessageSquareQuote,
  PackageCheck,
  PackageOpen,
  PackagePlus,
  ReceiptText,
  Settings2,
  ShoppingBag,
  Sparkles,
  Tags,
  Truck,
  Users,
  Wallet,
  Warehouse,
} from 'lucide-react'

export type Group = 'main' | 'sales' | 'buying' | 'stock' | 'settings'

export interface Module {
  to: string
  label: string
  short: string
  icon: LucideIcon
  group: Group
  keywords?: string
  hint?: string
}

/** The modules, in the order the business works: sell, buy, keep stock. */
export const MODULES: Module[] = [
  { to: '/', label: 'Home', short: 'Home', icon: Home, group: 'main', keywords: 'dashboard overview' },
  { to: '/assistant', label: 'Assistant', short: 'Assistant', icon: Sparkles, group: 'main', keywords: 'ai chat ask gemini' },
  { to: '/insights', label: 'Insights', short: 'Insights', icon: BarChart3, group: 'main', keywords: 'analytics reports ageing reorder conversion' },
  { to: '/fulfilment', label: 'Fulfilment', short: 'Fulfilment', icon: PackageCheck, group: 'main', keywords: 'deliver ready short on order' },
  { to: '/finance', label: 'Finance', short: 'Finance', icon: Wallet, group: 'main', keywords: 'money receivables payables payments owed collections' },
  { to: '/tasks', label: 'Follow-ups', short: 'Follow-ups', icon: ListChecks, group: 'main', keywords: 'tasks reminders to do' },
  { to: '/enquiries', label: 'Enquiries', short: 'Enquiries', icon: MessageSquareQuote, group: 'sales', keywords: 'quote deal lead', hint: 'Quotes and leads' },
  { to: '/orders', label: 'Sales Orders', short: 'Orders', icon: ReceiptText, group: 'sales', keywords: 'so sell', hint: 'What customers bought' },
  { to: '/customers', label: 'Customers', short: 'Customers', icon: Users, group: 'sales', keywords: 'client buyer', hint: 'Who buys from you' },
  { to: '/price-lists', label: 'Price Lists', short: 'Price lists', icon: Tags, group: 'sales', keywords: 'pricing rates dealer contractor price level discount', hint: 'Negotiated prices' },
  { to: '/purchase-orders', label: 'Purchase Orders', short: 'Purchases', icon: ClipboardList, group: 'buying', keywords: 'po buy', hint: 'What you ordered' },
  { to: '/receipts', label: 'Goods Receipts', short: 'Receipts', icon: PackageOpen, group: 'buying', keywords: 'grn arrival receive', hint: 'Goods that arrived' },
  { to: '/suppliers', label: 'Suppliers', short: 'Suppliers', icon: Building2, group: 'buying', keywords: 'vendor', hint: 'Who you buy from' },
  { to: '/products', label: 'Products', short: 'Products', icon: Boxes, group: 'stock', keywords: 'sku item stock', hint: 'Catalogue and stock' },
  { to: '/stock-in', label: 'Stock In', short: 'Stock in', icon: PackagePlus, group: 'stock', keywords: 'receipt without po adhoc', hint: 'Stock without a purchase order' },
  { to: '/stock-count', label: 'Stock Count', short: 'Stock count', icon: ClipboardCheck, group: 'stock', keywords: 'physical verification adjustment damage loss shrinkage cycle count', hint: 'Count, damage and loss' },
  { to: '/integrations', label: 'Settings', short: 'Settings', icon: Settings2, group: 'settings', keywords: 'ai gemini whatsapp email tally integrations' },
]

export const GROUPS: { key: Group; label: string; icon: LucideIcon }[] = [
  { key: 'sales', label: 'Sales', icon: ShoppingBag },
  { key: 'buying', label: 'Buying', icon: Truck },
  { key: 'stock', label: 'Stock', icon: Warehouse },
]

export const moduleFor = (pathname: string) =>
  [...MODULES].sort((a, b) => b.to.length - a.to.length).find((module) => (module.to === '/' ? pathname === '/' : pathname.startsWith(module.to))) ?? MODULES[0]
