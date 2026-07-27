import { describe, expect, it } from 'vitest'
import {
  buildClaimProgress,
  progressInputFromParts,
  resolveNextAction,
} from './claimProgress'

describe('claimProgress', () => {
  it('cold start sends to onboarding', () => {
    const a = resolveNextAction(
      progressInputFromParts({
        profileIsEmpty: true,
        docsTotal: 0,
        readyDocs: 0,
        reviewPending: null,
        conditionCount: 0,
        analysisDone: false,
        hasPlan: false,
        fileReady: false,
      }),
    )
    expect(a.route).toBe('/onboarding')
  })

  it('does not reopen profile when setup is non-empty', () => {
    const steps = buildClaimProgress(
      progressInputFromParts({
        profileIsEmpty: false,
        readyDocs: 2,
        reviewPending: 1,
        conditionCount: 0,
        analysisDone: false,
        hasPlan: false,
        fileReady: false,
      }),
    )
    expect(steps.find((s) => s.id === 'profile')?.done).toBe(true)
    expect(steps.find((s) => s.current)?.id).toBe('review')
  })

  it('processing overrides next incomplete step', () => {
    const a = resolveNextAction(
      progressInputFromParts({
        profileIsEmpty: false,
        readyDocs: 1,
        processingDocs: 3,
        reviewPending: 0,
        conditionCount: 0,
        analysisDone: false,
        hasPlan: false,
        fileReady: false,
      }),
    )
    expect(a.stepId).toBe('processing')
    expect(a.busy).toBe(true)
  })

  it('stable order has seven main steps', () => {
    const steps = buildClaimProgress(
      progressInputFromParts({
        profileIsEmpty: true,
        readyDocs: 0,
        reviewPending: null,
        conditionCount: 0,
        analysisDone: false,
        hasPlan: false,
        fileReady: false,
      }),
    )
    expect(steps.map((s) => s.id)).toEqual([
      'profile',
      'records',
      'review',
      'case',
      'analysis',
      'plan',
      'file',
    ])
  })
})
