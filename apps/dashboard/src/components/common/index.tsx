// Common reusable components

import React, { forwardRef } from 'react'
import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { ReactNode } from 'react'

export function cn(...inputs: (string | boolean | undefined | null)[]): string {
  return twMerge(clsx(inputs))
}

// Button component
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', loading, leftIcon, rightIcon, children, disabled, ...props }, ref) => {
    const baseStyles = 'inline-flex items-center justify-center gap-1.5 font-medium rounded-md transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg-primary disabled:opacity-50 disabled:cursor-not-allowed'
    
    const variants = {
      primary: 'bg-accent text-white hover:bg-accent-secondary active:bg-accent/80',
      secondary: 'bg-bg-elevated text-text-primary border border-border-subtle hover:bg-bg-panel hover:border-border-primary active:bg-bg-secondary',
      ghost: 'bg-transparent text-text-secondary hover:bg-bg-elevated hover:text-text-primary active:bg-bg-secondary',
      danger: 'bg-error/15 text-error border border-error/30 hover:bg-error/25 hover:border-error/50 active:bg-error/20',
    }

    const sizes = {
      sm: 'px-2.5 py-1 text-metadata gap-1',
      md: 'px-3 py-1.5 text-body gap-1.5',
      lg: 'px-4 py-2 text-body gap-2',
    }

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading && (
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        )}
        {!loading && leftIcon}
        {children}
        {!loading && rightIcon}
      </button>
    )
  }
)

Button.displayName = 'Button'

// Input component
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
  helpText?: string
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, helperText, helpText, leftIcon, rightIcon, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')
    const text = helperText || helpText

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="block text-metadata text-text-muted mb-1.5">
            {label}
          </label>
        )}
        <div className="relative">
          {leftIcon && (
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none">
              {leftIcon}
            </div>
          )}
          <input
            ref={ref}
            id={inputId}
            className={cn(
              'w-full px-3 py-2 text-body bg-bg-elevated border rounded-md placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-bg-primary transition-colors duration-fast disabled:opacity-50 disabled:cursor-not-allowed',
              leftIcon ? 'pl-10' : '',
              rightIcon ? 'pr-10' : '',
              error ? 'border-error/50 focus:ring-error focus:border-error' : 'border-border-subtle focus:ring-accent focus:border-transparent',
              className
            )}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={error ? `${inputId}-error` : text ? `${inputId}-helper` : undefined}
            {...props}
          />
          {rightIcon && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none">
              {rightIcon}
            </div>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} className="mt-1.5 text-metadata text-error" role="alert">
            {error}
          </p>
        )}
        {text && !error && (
          <p id={`${inputId}-helper`} className="mt-1.5 text-metadata text-text-muted">
            {text}
          </p>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'

// Textarea component
interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
  helperText?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, helperText, id, ...props }, ref) => {
    const textareaId = id || label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={textareaId} className="block text-metadata text-text-muted mb-1.5">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={textareaId}
          className={cn(
            'w-full px-3 py-2 text-body bg-bg-elevated border rounded-md placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-bg-primary transition-colors duration-fast disabled:opacity-50 disabled:cursor-not-allowed font-mono',
            error ? 'border-error/50 focus:ring-error focus:border-error' : 'border-border-subtle focus:ring-accent focus:border-transparent',
            className
          )}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={error ? `${textareaId}-error` : helperText ? `${textareaId}-helper` : undefined}
          {...props}
        />
        {error && (
          <p id={`${textareaId}-error`} className="mt-1.5 text-metadata text-error" role="alert">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p id={`${textareaId}-helper`} className="mt-1.5 text-metadata text-text-muted">
            {helperText}
          </p>
        )}
      </div>
    )
  }
)

Textarea.displayName = 'Textarea'

// Select component
interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
  helperText?: string
  options: Array<{ value: string; label: string }>
  placeholder?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, error, helperText, options, placeholder, id, ...props }, ref) => {
    const selectId = id || label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={selectId} className="block text-metadata text-text-muted mb-1.5">
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          className={cn(
            'w-full px-3 py-2 text-body bg-bg-elevated border rounded-md appearance-none focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-bg-primary transition-colors duration-fast disabled:opacity-50 disabled:cursor-not-allowed',
            error ? 'border-error/50 focus:ring-error focus:border-error' : 'border-border-subtle focus:ring-accent focus:border-transparent',
            className
          )}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={error ? `${selectId}-error` : helperText ? `${selectId}-helper` : undefined}
          {...props}
        >
          {placeholder && <option value="" disabled>{placeholder}</option>}
          {options.map(opt => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {error && (
          <p id={`${selectId}-error`} className="mt-1.5 text-metadata text-error" role="alert">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p id={`${selectId}-helper`} className="mt-1.5 text-metadata text-text-muted">
            {helperText}
          </p>
        )}
      </div>
    )
  }
)

Select.displayName = 'Select'

// Badge component
interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'outline'
  dot?: boolean
}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = 'neutral', dot, children, ...props }, ref) => {
    const variants = {
      success: 'bg-success/15 text-success border border-success/30',
      warning: 'bg-warning/15 text-warning border border-warning/30',
      error: 'bg-error/15 text-error border border-error/30',
      info: 'bg-info/15 text-info border border-info/30',
      neutral: 'bg-bg-elevated text-text-secondary border border-border-subtle',
      outline: 'bg-transparent text-text-secondary border border-border-primary',
    }

    return (
      <span
        ref={ref}
        className={cn(
          'inline-flex items-center px-2 py-0.5 text-metadata font-medium rounded-full',
          variants[variant],
          className
        )}
        {...props}
      >
        {dot && (
          <span
            className={cn(
              'w-1.5 h-1.5 rounded-full mr-1.5',
              variant === 'success' && 'bg-success',
              variant === 'warning' && 'bg-warning',
              variant === 'error' && 'bg-error',
              variant === 'info' && 'bg-info',
              variant === 'neutral' && 'bg-text-muted'
            )}
          />
        )}
        {children}
      </span>
    )
  }
)

Badge.displayName = 'Badge'

// StatusBadge for request status
export function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
    OK: 'success',
    HIT: 'success',
    MISS: 'warning',
    SKIPPED: 'info',
    WRITE: 'info',
    ERROR: 'error',
    TIMEOUT: 'error',
    RATE_LIMITED: 'warning',
    PENDING: 'info',
    healthy: 'success',
    degraded: 'warning',
    down: 'error',
    active: 'success',
    expired: 'warning',
    evicted: 'error',
    invalidated: 'error',
  }

  const variant = variants[status.toUpperCase()] || 'neutral'
  return <Badge variant={variant} dot>{status.toUpperCase()}</Badge>
}

// Card component
interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  elevated?: boolean
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ className, elevated, padding = 'md', children, ...props }, ref) => {
    const paddingClasses = {
      none: 'p-0',
      sm: 'p-3',
      md: 'p-4',
      lg: 'p-6',
    }

    return (
      <div
        ref={ref}
        className={cn(
          elevated ? 'panel-elevated' : 'panel',
          paddingClasses[padding],
          className
        )}
        {...props}
      >
        {children}
      </div>
    )
  }
)

Card.displayName = 'Card'

// CardHeader, CardContent, CardFooter
export const CardHeader = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('mb-4', className)} {...props} />
  )
)

CardHeader.displayName = 'CardHeader'

export const CardContent = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn(className)} {...props} />
  )
)

CardContent.displayName = 'CardContent'

export const CardFooter = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('mt-4 pt-4 border-t border-border-subtle flex items-center gap-2', className)} {...props} />
  )
)

CardFooter.displayName = 'CardFooter'

// Table components
interface TableProps extends React.TableHTMLAttributes<HTMLTableElement> {}

export const Table = forwardRef<HTMLTableElement, TableProps>(
  ({ className, ...props }, ref) => (
    <table ref={ref} className={cn('w-full text-left text-table', className)} {...props} />
  )
)

Table.displayName = 'Table'

export const TableHeader = forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <thead ref={ref} className={cn(className)} {...props} />
  )
)

TableHeader.displayName = 'TableHeader'

export const TableBody = forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tbody ref={ref} className={cn(className)} {...props} />
  )
)

TableBody.displayName = 'TableBody'

export const TableRow = forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement> & { selected?: boolean }>(
  ({ className, selected, ...props }, ref) => (
    <tr
      ref={ref}
      className={cn(
        'transition-colors duration-fast',
        selected && 'bg-bg-elevated/50',
        className
      )}
      {...props}
    />
  )
)

TableRow.displayName = 'TableRow'

export const TableHead = forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <th
      ref={ref}
      className={cn('px-3 py-2 text-metadata font-medium text-text-muted uppercase tracking-wider bg-bg-secondary border-b border-border-subtle', className)}
      {...props}
    />
  )
)

TableHead.displayName = 'TableHead'

export const TableCell = forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <td ref={ref} className={cn('px-3 py-2 border-b border-border-subtle/50', className)} {...props} />
  )
)

TableCell.displayName = 'TableCell'

// Divider
interface DividerProps extends React.HTMLAttributes<HTMLDivElement> {
  orientation?: 'horizontal' | 'vertical'
}

export const Divider = forwardRef<HTMLDivElement, DividerProps>(
  ({ className, orientation = 'horizontal', ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'bg-border-subtle',
        orientation === 'horizontal' ? 'h-px w-full' : 'w-px h-full',
        className
      )}
      {...props}
    />
  )
)

Divider.displayName = 'Divider'

// EmptyState
interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  action?: ReactNode
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state-icon">{icon}</div>}
      <h3 className="empty-state-title">{title}</h3>
      {description && <p className="empty-state-description">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

// LoadingSkeleton
interface LoadingSkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'text' | 'card' | 'table-row' | 'chart'
  lines?: number
}

export function LoadingSkeleton({ className, variant = 'text', lines = 1, ...props }: LoadingSkeletonProps) {
  if (variant === 'card') {
    return (
      <div className={cn('panel p-4 space-y-3', className)} {...props}>
        <div className="h-4 w-3/4 loading-skeleton rounded" />
        <div className="h-8 w-1/2 loading-skeleton rounded" />
        <div className="h-4 w-full loading-skeleton rounded" />
        <div className="h-4 w-2/3 loading-skeleton rounded" />
      </div>
    )
  }

  if (variant === 'table-row') {
    return (
      <tr className={cn(className)} {...props}>
        <td className="px-3 py-2"><div className="h-4 w-20 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-24 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-16 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-16 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-20 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-16 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-20 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-16 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-16 loading-skeleton rounded" /></td>
        <td className="px-3 py-2"><div className="h-4 w-16 loading-skeleton rounded" /></td>
      </tr>
    )
  }

  return (
    <div className={cn('space-y-2', className)} {...props}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className={cn('loading-skeleton rounded', i === lines - 1 ? 'w-3/4' : 'w-full')} style={{ height: '1rem' }} />
      ))}
    </div>
  )
}

// Tooltip
interface TooltipProps {
  content: ReactNode
  children: ReactNode
  position?: 'top' | 'bottom' | 'left' | 'right'
  delay?: number
}

export function Tooltip({ content, children, position = 'top', delay = 200 }: TooltipProps) {
  const [visible, setVisible] = React.useState(false)
  const timeoutRef = React.useRef<ReturnType<typeof setTimeout>>()
  const childRef = React.useRef<HTMLElement>(null)

  const show = () => {
    timeoutRef.current = setTimeout(() => setVisible(true), delay)
  }

  const hide = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    setVisible(false)
  }

  const positions = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }

  return (
    <div className="relative inline-block" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      <span ref={childRef}>{children}</span>
      {visible && (
        <div
          className={cn(
            'fixed z-50 chart-tooltip whitespace-nowrap animate-in fade-in-0 zoom-in-95 duration-fast',
            positions[position]
          )}
          style={{ transformOrigin: position === 'top' ? 'bottom' : position === 'bottom' ? 'top' : 'center' }}
        >
          <div className="relative">{content}</div>
          <div
            className={cn(
              'absolute w-0 h-0 border-4 border-transparent',
              position === 'top' && 'bottom-[-8px] left-1/2 -translate-x-1/2 border-t-accent',
              position === 'bottom' && 'top-[-8px] left-1/2 -translate-x-1/2 border-b-accent',
              position === 'left' && 'right-[-8px] top-1/2 -translate-y-1/2 border-l-accent',
              position === 'right' && 'left-[-8px] top-1/2 -translate-y-1/2 border-r-accent'
            )}
          />
        </div>
      )}
    </div>
  )
}

// Dropdown
interface DropdownProps {
  trigger: ReactNode
  content: ReactNode
  align?: 'left' | 'right'
}

export function Dropdown({ trigger, content, align = 'right' }: DropdownProps) {
  const [open, setOpen] = React.useState(false)
  const dropdownRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div ref={dropdownRef} className="relative inline-block">
      <div onClick={() => setOpen(!open)}>{trigger}</div>
      {open && (
        <div
          className={cn(
            'fixed z-50 panel-elevated shadow-drawer rounded-panel min-w-[200px] py-1 animate-in fade-in-0 zoom-in-95 duration-fast',
            align === 'right' ? 'right-0' : 'left-0'
          )}
        >
          {content}
        </div>
      )}
    </div>
  )
}

// Tabs
interface TabsProps {
  defaultValue: string
  value?: string
  onValueChange?: (value: string) => void
  children: ReactNode
  className?: string
}

interface TabsListProps {
  children: ReactNode
  className?: string
}

interface TabsTriggerProps {
  value: string
  children: ReactNode
  disabled?: boolean
  className?: string
}

interface TabsContentProps {
  value: string
  children: ReactNode
  className?: string
}

const TabsContext = React.createContext<{
  value: string
  onChange: (value: string) => void
} | null>(null)

export function Tabs({ defaultValue, value, onValueChange, children, className }: TabsProps) {
  const [internalValue, setInternalValue] = React.useState(defaultValue)
  const controlled = value !== undefined
  const currentValue = controlled ? value : internalValue

  const handleChange = (newValue: string) => {
    if (!controlled) setInternalValue(newValue)
    onValueChange?.(newValue)
  }

  return (
    <TabsContext.Provider value={{ value: currentValue, onChange: handleChange }}>
      <div className={cn(className)}>{children}</div>
    </TabsContext.Provider>
  )
}

export function TabsList({ children, className }: TabsListProps) {
  return (
    <div
      role="tablist"
      className={cn(
        'inline-flex items-center gap-1 bg-bg-elevated rounded-md p-1',
        className
      )}
    >
      {children}
    </div>
  )
}

export function TabsTrigger({ value, children, disabled, className }: TabsTriggerProps) {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error('TabsTrigger must be used within Tabs')

  const { value: currentValue, onChange } = context
  const isActive = currentValue === value

  return (
    <button
      role="tab"
      aria-selected={isActive}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={() => !disabled && onChange(value)}
      className={cn(
        'px-3 py-1.5 text-body font-medium rounded-md transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg-primary',
        isActive
          ? 'bg-bg-panel text-text-primary shadow-sm'
          : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary',
        disabled && 'opacity-50 cursor-not-allowed',
        className
      )}
    >
      {children}
    </button>
  )
}

export function TabsContent({ value, children, className }: TabsContentProps) {
  const context = React.useContext(TabsContext)
  if (!context) throw new Error('TabsContent must be used within Tabs')

  const { value: currentValue } = context

  if (currentValue !== value) return null

  return <div role="tabpanel" className={cn(className)}>{children}</div>
}

// Separator
export const Separator = forwardRef<HTMLDivElement, DividerProps>(
  ({ className, orientation = 'horizontal', ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'bg-border-subtle',
        orientation === 'horizontal' ? 'h-px w-full' : 'w-px h-full',
        className
      )}
      {...props}
    />
  )
)

Separator.displayName = 'Separator'

// ScrollArea
interface ScrollAreaProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string
}

export const ScrollArea = forwardRef<HTMLDivElement, ScrollAreaProps>(
  ({ className, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('overflow-auto scrollbar-hide', className)}
      {...props}
    >
      {children}
    </div>
  )
)

ScrollArea.displayName = 'ScrollArea'

// Switch component (with optional label for inline use)
interface SwitchProps {
  label?: string
  description?: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
  size?: 'sm' | 'md'
}

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(
  ({ label, description, checked, onChange, disabled, size = 'md', ...props }, ref) => {
    const isInline = !label

    if (isInline) {
      return (
        <button
          ref={ref}
          role="switch"
          aria-checked={checked}
          onClick={() => !disabled && onChange(!checked)}
          disabled={disabled}
          className={cn(
            'flex items-center justify-center transition-colors duration-fast disabled:opacity-50 disabled:cursor-not-allowed',
            size === 'sm' ? 'w-8 h-5' : 'w-11 h-6',
            props.className
          )}
          {...props}
        >
          <div
            className={cn(
              'relative rounded-full transition-colors duration-fast',
              size === 'sm' ? 'w-10 h-4' : 'w-11 h-6',
              checked ? 'bg-accent' : 'bg-border-primary'
            )}
          >
            <div
              className={cn(
                'absolute top-0.5 left-0.5 rounded-full bg-white shadow-md transition-transform duration-fast',
                size === 'sm' ? 'w-3 h-3' : 'w-5 h-5',
                checked ? 'translate-x-5' : 'translate-x-0'
              )}
            />
          </div>
        </button>
      )
    }

    return (
      <button
        ref={ref}
        role="switch"
        aria-checked={checked}
        onClick={() => !disabled && onChange(!checked)}
        disabled={disabled}
        className={cn(
          'flex items-center gap-3 w-full px-3 py-2 bg-bg-elevated border border-border-subtle rounded-lg hover:bg-bg-panel transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
          props.className
        )}
        {...props}
      >
        <div
          className={cn(
            'relative w-11 h-6 rounded-full transition-colors duration-fast',
            checked ? 'bg-accent' : 'bg-border-primary'
          )}
        >
          <div
            className={cn(
              'absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow-md transition-transform duration-fast',
              checked ? 'translate-x-5' : 'translate-x-0'
            )}
          />
        </div>
        <div className="flex-1 text-left">
          <p className="text-body font-medium">{label}</p>
          {description && <p className="text-metadata text-text-muted">{description}</p>}
        </div>
      </button>
    )
  }
)

// Progress component
interface ProgressProps {
  value: number
  max?: number
  className?: string
}

export const Progress = forwardRef<HTMLDivElement, ProgressProps>(
  ({ value, max = 100, className }, ref) => {
    const percentage = Math.min(100, Math.max(0, (value / max) * 100))
    return (
      <div
        ref={ref}
        className={cn('w-full h-2 bg-bg-elevated rounded-full overflow-hidden', className)}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
      >
        <div
          className="h-full bg-accent rounded-full transition-all duration-500"
          style={{ width: `${percentage}%` }}
        />
      </div>
    )
  }
)

Progress.displayName = 'Progress'