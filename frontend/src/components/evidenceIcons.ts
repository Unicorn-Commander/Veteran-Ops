import { Activity, ClipboardList, FileSignature, FileText, MessageSquare, Shield, Stethoscope, type LucideIcon } from 'lucide-react'
import type { EvidenceKind } from '../types'

// Evidence-kind icon map. Shared by Evidence.tsx and ConditionDetail.tsx.
export const EVIDENCE_KIND_ICONS: Record<EvidenceKind, LucideIcon> = {
  diagnosis: Stethoscope,
  service_record: Shield,
  nexus_letter: FileSignature,
  dbq: ClipboardList,
  lay_statement: MessageSquare,
  continuity: Activity,
  treatment_record: FileText,
  other: FileText,
}
