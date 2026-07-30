import type { ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
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
import { TooltipProvider } from '@/components/ui/tooltip'
import { useTheme } from './theme/useTheme'
import { WIZARD_STEPS, type WizardStep } from './wizardSteps'

interface AppShellProps {
  currentStep: WizardStep
  children: ReactNode
}

export function AppShell({ currentStep, children }: AppShellProps) {
  const { theme, toggleTheme } = useTheme()
  const currentIndex = WIZARD_STEPS.findIndex((step) => step.id === currentStep)

  return (
    <TooltipProvider>
      <SidebarProvider>
        <Sidebar collapsible="icon">
          <SidebarHeader>
            <span className="px-2 py-1 text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">IS IT WORTH IT</span>
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
            <Button
              variant="ghost"
              size="icon"
              aria-label={theme === 'dark' ? 'Przełącz na jasny motyw' : 'Przełącz na ciemny motyw'}
              onClick={toggleTheme}
            >
              {theme === 'dark' ? <Sun /> : <Moon />}
            </Button>
          </SidebarFooter>
          <SidebarRail />
        </Sidebar>
        <SidebarInset>
          <header className="flex items-center gap-2 p-2 md:hidden">
            <SidebarTrigger />
          </header>
          {children}
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
