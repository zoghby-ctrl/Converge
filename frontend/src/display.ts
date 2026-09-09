// Presentation aliases only: stored identifiers and provenance remain unchanged.
export const scenarioLabel = (id: string): string => ({
  signature: 'Road Incident Overview', signature_image: 'Multi-Signal Road Incident',
  context_signature: 'Road Incident with Local Context', context_archive: 'Historical Road Observations',
  missing_road_damage: 'Incomplete Road Condition Evidence', conflicting_water: 'Conflicting Water Reports',
  spatial_119m: 'Nearby Observations', spatial_121m: 'Separated Observations',
  time_5h59: 'Reports Within Six Hours', time_6h: 'Reports Six Hours Apart',
  time_over_6h: 'Reports Beyond Six Hours', chain_guard: 'Spread-Out Observations',
  road_incompatible: 'Different Road Segments',
}[id] ?? id.replaceAll('_', ' '))
const internalReviewer = /\bphase\s*\d|browser verification|development verification|hostile|\btest\b|fixture|\be2e\b/i
export const reviewerLabel = (name: string): string => internalReviewer.test(name) ? 'Demo reviewer' : name
export const roadLabel = (name: string): string => /^browser cached road$/i.test(name.trim()) ? 'Demo Road Observation' : name
