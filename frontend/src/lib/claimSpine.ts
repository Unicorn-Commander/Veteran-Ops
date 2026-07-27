/**
 * @deprecated Import from `./claimProgress` instead.
 * Thin re-exports so older imports keep working during the single-spine migration.
 */

export {
  buildClaimProgress as buildClaimSpineSteps,
  nextRingsAfterAnalysis as postAnalysisNextRings,
  toSpineSteps,
  type ClaimProgressInput as ClaimSpineInput,
  type ClaimProgressStep as ClaimSpineStepDef,
} from './claimProgress'

import { buildClaimProgress, type ClaimProgressInput } from './claimProgress'

/** First incomplete step, or the last step when everything is done. */
export function nextClaimSpineStep(input: ClaimProgressInput) {
  const steps = buildClaimProgress(input)
  return steps.find((s) => !s.done) ?? steps[steps.length - 1]
}
