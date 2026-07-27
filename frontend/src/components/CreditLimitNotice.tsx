import { ArrowRight, Wallet } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState } from './ui'

export function CreditLimitNotice({
  title = "You're out of credits",
  description = 'Add a top-up to keep reading, analyzing, and decoding your records.',
  actionLabel = 'Go to billing',
}: {
  title?: string
  description?: string
  actionLabel?: string
}) {
  return (
    <EmptyState
      hue="amber"
      icon={<Wallet size={22} />}
      title={title}
      description={description}
      action={
        <Link to="/billing" className="vo-btn-primary text-sm">
          {actionLabel} <ArrowRight size={15} />
        </Link>
      }
    />
  )
}
