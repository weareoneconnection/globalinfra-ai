import { getLocale } from 'next-intl/server';
import { JuryControlRoom } from '@/components/JuryControlRoom';
import {
  type GoldenThread,
  type SubmissionEvidence,
} from '@/components/CompetitionEvidence';
import { api } from '@/lib/api';

export default async function JuryModePage() {
  const [locale, golden, evidence] = await Promise.all([
    getLocale(),
    api<GoldenThread>('/competition/golden-thread'),
    api<SubmissionEvidence>('/competition/submission-evidence'),
  ]);

  return (
    <JuryControlRoom
      locale={locale}
      golden={golden}
      evidence={evidence}
    />
  );
}
