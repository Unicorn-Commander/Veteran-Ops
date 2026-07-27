/** Ephemeral hand-off key: Scenarios "load into calculator" stashes entries
 * here and navigates to /calculator, which reads + clears it on mount. Kept
 * out of the main token/theme keys so it's obviously session-scoped. */
export const SCENARIO_LOAD_KEY = 'vo_pending_scenario'
