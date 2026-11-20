import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  Boxes,
  Building2,
  ClipboardCheck,
  FileSignature,
  ClipboardList,
  Home,
  Megaphone,
  CalendarDays,
  WandSparkles,
  Workflow,
  Radio,
  LayoutDashboard,
  ChartNoAxesCombined,
  UserRoundSearch,
  ListChecks,
  MessageSquareQuote,
  PackageCheck,
  PackageOpen,
  PackagePlus,
  ReceiptText,
  Settings2,
  ShoppingBag,
  Sparkles,
  UsersRound,
  Truck,
  Users,
  Wallet,
  Warehouse,
} from 'lucide-react'

export type Group = 'main' | 'sales' | 'marketing' | 'buying' | 'stock' | 'settings'

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
  { to: '/customer-groups', label: 'Customer Groups', short: 'Groups', icon: UsersRound, group: 'sales', keywords: 'smart manual group segment rules tier gold dealer contractor discount price list pricing rates price level', hint: 'Customers and the prices they get' },
  { to: '/marketing', label: 'Marketing Home', short: 'Marketing', icon: LayoutDashboard, group: 'marketing', keywords: 'marketing promote promotion opportunities instagram whatsapp broadcast', hint: 'Opportunities and results' },
  { to: '/marketing/campaigns', label: 'Campaigns', short: 'Campaigns', icon: Megaphone, group: 'marketing', keywords: 'campaign offer broadcast post promotion', hint: 'Plan, approve and run' },
  { to: '/marketing/calendar', label: 'Content Calendar', short: 'Calendar', icon: CalendarDays, group: 'marketing', keywords: 'schedule posts calendar', hint: 'Posts and broadcasts by date' },
  { to: '/marketing/studio', label: 'AI Studio', short: 'Studio', icon: WandSparkles, group: 'marketing', keywords: 'creative image card caption template ai design', hint: 'Creatives and templates' },
  { to: '/marketing/audiences', label: 'Audiences', short: 'Audiences', icon: UserRoundSearch, group: 'marketing', keywords: 'segment audience consent opt in birthday', hint: 'Who to reach, and consent' },
  { to: '/marketing/channels', label: 'Instagram & WhatsApp', short: 'Channels', icon: Radio, group: 'marketing', keywords: 'instagram whatsapp comments templates connect', hint: 'Accounts, posts, comments' },
  { to: '/marketing/automations', label: 'Marketing Automations', short: 'Automations', icon: Workflow, group: 'marketing', keywords: 'trigger rule automation agent', hint: 'Triggers and agents' },
  { to: '/marketing/analytics', label: 'Marketing Analytics', short: 'Analytics', icon: ChartNoAxesCombined, group: 'marketing', keywords: 'roi results attribution performance', hint: 'What it earned' },
  { to: '/purchase-orders', label: 'Purchase Orders', short: 'Purchases', icon: ClipboardList, group: 'buying', keywords: 'po buy', hint: 'What you ordered' },
  { to: '/receipts', label: 'Goods Receipts', short: 'Receipts', icon: PackageOpen, group: 'buying', keywords: 'grn arrival receive', hint: 'Goods that arrived' },
  { to: '/suppliers', label: 'Suppliers', short: 'Suppliers', icon: Building2, group: 'buying', keywords: 'vendor', hint: 'Who you buy from' },
  { to: '/transporters', label: 'Transporters', short: 'Transport', icon: Truck, group: 'buying', keywords: 'transport lorry truck tempo freight vehicle driver booking bilty lr carrier', hint: 'Vehicles, rates and bookings' },
  { to: '/rate-contracts', label: 'Rate Contracts', short: 'Contracts', icon: FileSignature, group: 'buying', keywords: 'rate contract agreement annual rate mill project price period commitment', hint: 'Agreed rates for a period' },
  { to: '/products', label: 'Products', short: 'Products', icon: Boxes, group: 'stock', keywords: 'sku item stock', hint: 'Catalogue and stock' },
  { to: '/stock-in', label: 'Stock In', short: 'Stock in', icon: PackagePlus, group: 'stock', keywords: 'receipt without po adhoc', hint: 'Stock without a purchase order' },
  { to: '/warehouses', label: 'Warehouses', short: 'Warehouses', icon: Warehouse, group: 'stock', keywords: 'godown yard shop site location transfer move freight landed cost transit', hint: 'Godowns and transfers' },
  { to: '/stock-count', label: 'Stock Count', short: 'Stock count', icon: ClipboardCheck, group: 'stock', keywords: 'physical verification adjustment damage loss shrinkage cycle count', hint: 'Count, damage and loss' },
  { to: '/integrations', label: 'Settings', short: 'Settings', icon: Settings2, group: 'settings', keywords: 'ai gemini whatsapp email tally integrations' },
]

export const GROUPS: { key: Group; label: string; icon: LucideIcon }[] = [
  { key: 'sales', label: 'Sales', icon: ShoppingBag },
  { key: 'marketing', label: 'Marketing', icon: Megaphone },
  { key: 'buying', label: 'Buying', icon: Truck },
  { key: 'stock', label: 'Stock', icon: Warehouse },
]

export const moduleFor = (pathname: string) =>
  [...MODULES].sort((a, b) => b.to.length - a.to.length).find((module) => (module.to === '/' ? pathname === '/' : pathname.startsWith(module.to))) ?? MODULES[0]
