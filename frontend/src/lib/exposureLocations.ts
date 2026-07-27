/**
 * Curated exposure / deployment places for profile autocomplete.
 * Mirrors common VA presumptive "where" windows (PACT, AO, Gulf War, Lejeune, etc.).
 * Free-text still allowed — this is suggestions only.
 */
export const EXPOSURE_LOCATION_SUGGESTIONS: string[] = [
  // Herbicide / AO
  'Vietnam',
  'Republic of Vietnam',
  'Da Nang',
  'Saigon',
  'Cam Ranh Bay',
  'Korean DMZ',
  'Thailand',
  'Laos',
  'Cambodia',
  'Guam',
  'American Samoa',
  'Johnston Atoll',
  // PACT / burn pits / SW Asia
  'Iraq',
  'Afghanistan',
  'Kuwait',
  'Saudi Arabia',
  'Bahrain',
  'Qatar',
  'Oman',
  'UAE',
  'United Arab Emirates',
  'Syria',
  'Jordan',
  'Djibouti',
  'Egypt',
  'Lebanon',
  'Yemen',
  'Somalia',
  'Uzbekistan',
  'Persian Gulf',
  // Camp Lejeune
  'Camp Lejeune',
  'MCAS New River',
  // Common CONUS / other
  'Camp Pendleton',
  'Fort Bragg',
  'Fort Liberty',
  'Fort Hood',
  'Fort Cavazos',
  'Fort Campbell',
  'Fort Benning',
  'Fort Moore',
  'Camp Casey',
  'Okinawa',
  'Germany',
  'Korea',
  'South Korea',
  'Philippines',
  'Diego Garcia',
  'Enewetak Atoll',
  'Hiroshima',
  'Nagasaki',
].sort((a, b) => a.localeCompare(b))

export function filterLocationSuggestions(query: string, already: string[], limit = 8): string[] {
  const q = query.trim().toLowerCase()
  const have = new Set(already.map((s) => s.toLowerCase()))
  if (!q) {
    return EXPOSURE_LOCATION_SUGGESTIONS.filter((s) => !have.has(s.toLowerCase())).slice(0, limit)
  }
  return EXPOSURE_LOCATION_SUGGESTIONS.filter(
    (s) => !have.has(s.toLowerCase()) && s.toLowerCase().includes(q),
  ).slice(0, limit)
}
