# Synapse UI Design System

## Colors (Tailwind Config)
- **Primary bg**: `#09090B` (`bg-bg-primary`) — near-black base
- **Secondary bg**: `#0D0D0F` (`bg-bg-secondary`) — cards, panels
- **Sidebar bg**: `#0B0B0D` (`bg-bg-sidebar`) — darker than primary
- **Panel bg**: `#111113` (`bg-bg-panel`) — elevated surfaces
- **Elevated bg**: `#151518` (`bg-bg-elevated`) — drawers, modals
- **Borders**: `#1B1B1F` (`border-border-subtle`), `#242428` (`border-border-primary`)
- **Text**: `#F4F4F5` (primary), `#A1A1AA` (secondary), `#71717A` (muted), `#52525B` (disabled)
- **Accent**: `#FF6B3D` (`accent`) — CTAs, highlights, active states
- **Accent secondary**: `#FF8A5B` (`accent-secondary`)
- **Accent muted**: `rgba(255, 107, 61, 0.15)` (`accent-muted`)
- **Status**: success `#22C55E`, warning `#F59E0B`, error `#EF4444`, info `#60A5FA`

## Typography
- **Font**: `Inter` (UI), `JetBrains Mono` (code/data)
- **Scale**: `text-metadata` (11px/16px), `text-body-sm` (12px/18px), `text-body` (13px/20px), `text-section-title` (16px/24px), `text-page-title` (24px/32px)
- **Code**: `text-code` (12px/18px, JetBrains Mono)

## Spacing & Radius
- **Spacing**: 4px base (`p-1` = 4px, `p-2` = 8px, `p-3` = 12px, `p-4` = 16px, `p-5` = 20px, `p-6` = 24px, `p-8` = 32px)
- **Radius**: `rounded-panel` (8px), `rounded-panel-lg` (10px), plus standard `rounded-sm` (4px), `rounded-md` (6px), `rounded-lg` (8px), `rounded-full`

## Shadows
- `shadow-subtle`: `0 1px 3px rgba(0,0,0,0.3)` — subtle elevation
- `shadow-drawer`: `0 4px 20px rgba(0,0,0,0.4)` — drawers, modals, dropdowns

## Animation
- **Duration**: `duration-fast` (120ms), `duration-normal` (160ms), `duration-slow` (200ms)
- **Easing**: `ease-out` default
- **Transitions**: `transition-all` for layout, `transition-colors` for UI

## Component Patterns
| Component | Variants | Key Classes |
|-----------|----------|-------------|
| Button | primary, secondary, ghost, danger | `transition-colors duration-fast` |
| Input | default, error | `bg-bg-input border-border-subtle focus:border-accent` |
| Badge | default, success, warning, error, outline | semantic bg/text pairs |
| Card | default, elevated | `bg-bg-secondary border-border-subtle` / `bg-bg-elevated` |
| Switch | inline, label | `peer` + `after:translate-x` pattern |
| Select | default, error | same as Input |
| Tabs | default, bordered | `border-border-subtle` active: `text-accent` |

## Layout
- **Sidebar**: 248px expanded / 64px collapsed, fixed left, z-40
- **Header**: sticky top, z-30, 64px height
- **Content max-width**: 1600px (`max-w-[1600px] mx-auto`)
- **Page padding**: `p-6`
- **Grid gaps**: `gap-4` (16px) standard, `gap-6` (24px) loose

## Dark-First Rules
1. Never use `bg-white` or `text-black`
2. Use semantic tokens: `bg-bg-primary`, `text-text-primary`, `border-border-subtle`
3. Accent only for primary actions, not decorative
4. Hover states: `hover:bg-accent/10`, `hover:border-accent/30`
5. Active/selected: `bg-accent/10 text-accent border-accent/30`
6. Disabled: `opacity-50 cursor-not-allowed`, text: `text-text-disabled`

## State Indicators
- **Connected/Success**: `bg-success` (green `#22C55E`)
- **Disconnected/Error**: `bg-error` (red `#EF4444`)
- **Warning/Pending**: `bg-warning` (amber `#F59E0B`)
- **Info**: `bg-info` (blue `#60A5FA`)
- **Demo mode**: `bg-warning/10 text-warning border-warning/30`

## Icons
- **Library**: Lucide React
- **Size**: `w-4 h-4` (inline), `w-5 h-5` (standalone), `w-8 h-8` (feature)
- **Color**: `text-text-muted` default, `text-accent` active, `text-text-primary` emphasis

## Responsive
- Mobile-first: sidebar collapses at `< lg` (1024px)
- Tables: horizontal scroll on mobile (`overflow-x-auto`)
- Charts: responsive containers, maintain aspect ratio
- Breakpoints: `sm` 640px, `md` 768px, `lg` 1024px, `xl` 1280px

## Data Display
- **Tables**: `text-table` (12px), striped rows `hover:bg-bg-panel`, sortable headers
- **Metrics**: `MetricCard` with trend sparkline, `CompactMetric` for dense grids
- **Charts**: Recharts with custom dark theme, accent color series
- **Code/Monospace**: `text-code` / `font-mono` for IDs, tokens, JSON