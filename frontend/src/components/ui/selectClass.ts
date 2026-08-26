// Width is deliberately not baked in here — MappingStep's 5 dropdowns want a fixed
// w-56 (stacked justify-between rows, a fixed right-hand control is the point), while
// ReportStep's 3 filters sit side by side in one flex row where a fixed 224px each
// would force a wrap. Callers pass their own width via `cn(SELECT_CLASS, 'w-…')`.
export const SELECT_CLASS =
  'h-8 rounded-lg border border-input bg-transparent px-2.5 py-1 text-base transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 md:text-sm dark:bg-input/30 dark:disabled:bg-input/80'
