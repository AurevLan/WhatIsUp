/**
 * Lightweight fuzzy subsequence matcher.
 *
 * Returns 0 when `query` does not appear (in order) inside `target`.
 * Returns a positive score otherwise — higher = better match. Scoring favours:
 *   - shorter targets
 *   - matches starting near the beginning
 *   - consecutive characters
 *
 * No external dependency. Designed for command palette / quick search.
 */
export function fuzzyScore(query, target) {
  if (!query) return 1
  if (!target) return 0
  const q = String(query).toLowerCase()
  const t = String(target).toLowerCase()
  let qi = 0
  let score = 0
  let consecutive = 0
  let firstMatchIdx = -1

  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t.charCodeAt(ti) === q.charCodeAt(qi)) {
      if (firstMatchIdx === -1) firstMatchIdx = ti
      consecutive += 1
      score += 1 + consecutive * 2
      // word boundary bonus
      if (ti === 0 || /[\s\-_./]/.test(t.charAt(ti - 1))) score += 3
      qi += 1
    } else {
      consecutive = 0
    }
  }

  if (qi < q.length) return 0
  // Penalise long targets and late first match.
  score -= Math.min(t.length / 8, 2)
  score -= Math.min(firstMatchIdx / 4, 3)
  return Math.max(score, 0.01)
}

export function fuzzyFilter(items, query, getter = (x) => x.name) {
  if (!query) return items
  return items
    .map((item) => ({ item, score: fuzzyScore(query, getter(item)) }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((entry) => entry.item)
}
