import { useState, type ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTheme } from './theme/useTheme'
import { WIZARD_STEPS, type WizardStep } from './wizardSteps'

interface AppShellProps {
  currentStep: WizardStep
  children: ReactNode
}

export function AppShell({ currentStep, children }: AppShellProps) {
  const { theme, toggleTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  const currentIndex = WIZARD_STEPS.findIndex((step) => step.id === currentStep)

  const handleOpenChange = (next: boolean) => {
    setOpen(next)
    setPinned(next)
  }

  const handleExpand = () => {
    if (!pinned) setOpen(true)
  }

  const handleCollapse = () => {
    if (!pinned) setOpen(false)
  }

  return (
    <TooltipProvider>
      <SidebarProvider open={open} onOpenChange={handleOpenChange}>
        <Sidebar
          collapsible="icon"
          onMouseEnter={handleExpand}
          onMouseLeave={handleCollapse}
          onFocus={handleExpand}
          onBlur={handleCollapse}
        >
          <SidebarHeader>
            <span className="flex items-baseline overflow-hidden px-2 py-1 text-sm font-semibold tracking-tight">
              <span>IS</span>
              <span className="grid grid-cols-[1fr] transition-[grid-template-columns] duration-200 ease-linear group-data-[collapsible=icon]:grid-cols-[0fr]">
                <span className="min-w-0 overflow-hidden whitespace-nowrap">{' IT WORTH IT'}</span>
              </span>
              <span>?</span>
            </span>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {WIZARD_STEPS.map((step, index) => (
                    <SidebarMenuItem key={step.id}>
                      <SidebarMenuButton
                        isActive={step.id === currentStep}
                        disabled={index > currentIndex}
                        tooltip={step.label}
                      >
                        <step.icon />
                        <span>{step.label}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter>
            {/* No `hidden={state !== "collapsed"}` here unlike SidebarMenuButton's tooltip: this
                button is icon-only in both sidebar states (no label span appears when expanded),
                so the tooltip stays the only visible affordance and must not be suppressed. */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={theme === 'dark' ? 'Przełącz na jasny motyw' : 'Przełącz na ciemny motyw'}
                  onClick={toggleTheme}
                >
                  {theme === 'dark' ? <Sun /> : <Moon />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right" align="center">
                {theme === 'dark' ? 'Przełącz na jasny motyw' : 'Przełącz na ciemny motyw'}
              </TooltipContent>
            </Tooltip>
          </SidebarFooter>
          <SidebarRail />
        </Sidebar>
        <SidebarInset>
          <ScrollArea className="flex-1 min-h-0">
            <header className="flex items-center gap-2 p-2 md:hidden">
              <SidebarTrigger />
            </header>
            {children}
          </ScrollArea>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
