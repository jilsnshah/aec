import { cn } from '@/lib/cn'

/** Slow, soft light-blue light behind a surface. Decoration only. */
export function Aurora({ className, strength = 1 }: { className?: string; strength?: number }) {
  return (
    <div className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)} aria-hidden="true" style={{ opacity: strength }}>
      <div className="absolute -top-[30%] -left-[10%] h-[70%] w-[60%] rounded-full bg-[radial-gradient(closest-side,rgb(124_196_255/0.16),transparent)] blur-2xl animate-aurora" />
      <div className="absolute -right-[15%] -bottom-[35%] h-[75%] w-[65%] rounded-full bg-[radial-gradient(closest-side,rgb(47_128_237/0.14),transparent)] blur-2xl animate-aurora [animation-delay:-9s]" />
    </div>
  )
}
