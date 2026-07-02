export function buildSeasonMap<T extends { season_number: number }>(
  episodes: T[],
): Map<number, T[]> {
  const map = new Map<number, T[]>()
  for (const ep of episodes) {
    const bucket = map.get(ep.season_number) ?? []
    bucket.push(ep)
    map.set(ep.season_number, bucket)
  }
  return map
}
