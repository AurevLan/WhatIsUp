// Symbol keys for provide/inject between MonitorDetailView and its detail
// sub-components. Using inject instead of props sidesteps the
// vue/no-mutating-props rule for the deliberate
// `state.x.value = …` pattern these tabs use against the shared
// composable return.

export const IncidentsStateKey = Symbol('IncidentsState')
export const SloStateKey = Symbol('SloState')
export const DnsStateKey = Symbol('DnsState')
export const AnnotationsStateKey = Symbol('AnnotationsState')
export const CustomMetricsStateKey = Symbol('CustomMetricsState')
export const AlertSetupStateKey = Symbol('AlertSetupState')
export const PatchStateKey = Symbol('PatchState')
export const DependenciesStateKey = Symbol('DependenciesState')
export const MaintenanceStateKey = Symbol('MaintenanceState')
