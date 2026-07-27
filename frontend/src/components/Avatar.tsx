import { useState } from 'react'

/** Two-letter initials from a name (or email fallback) — the avatar's graceful
 * fallback when there's no photo (native accounts) or the image fails to load. */
export function avatarInitials(name?: string | null, email?: string | null): string {
  const base = name?.trim() || email || ''
  const parts = base.split(/[\s@.]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || 'V'
}

/** The user's avatar: their Unicorn Commander profile photo (from the Keycloak
 * `picture` claim, delivered on the User as `avatar_url`) when present, otherwise
 * their initials on the brand tile. If the image 404s/blocks, it falls back to the
 * initials too — so this is always safe to render. */
export function UserAvatar({
  name,
  email,
  src,
  size = 36,
  className = '',
  title,
}: {
  name?: string | null
  email?: string | null
  src?: string | null
  size?: number
  className?: string
  title?: string
}) {
  const [failed, setFailed] = useState(false)
  const showImg = !!src && !failed
  return (
    <div
      className={`vo-logo-tile flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full font-bold text-white shadow-sm ${className}`}
      style={{ width: size, height: size, fontSize: Math.max(10, Math.round(size * 0.34)) }}
      title={title ?? email ?? undefined}
      aria-hidden="true"
    >
      {showImg ? (
        <img
          src={src as string}
          alt=""
          className="h-full w-full object-cover"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        avatarInitials(name, email)
      )}
    </div>
  )
}
