// Central map for the incident network verdict (plan_cap_v2 §3a — "is it my
// service, or the network between it and my users?"). One place so the
// compact badge (components/shared/NetworkVerdictBadge.vue) and any view that
// needs the full sentence (e.g. MonitorDetailView's incident banner) never
// drift into two different wordings for the same verdict.
//
// `service_down` and `inconclusive` are included here (the badge renders all
// four) even though plan_cap_v2 keeps `service_down` implicit and adds
// nothing for `inconclusive` in the *alert* body — that's a decision about
// the alert text, not about what the badge shows once you're already
// looking at the incident.
const VERDICT_INFO = {
  service_down: {
    cls: 'verdict-badge--service',
    labelKey: 'incidents.verdict_short_service_down',
    explainKey: 'incidents.verdict_service_down_tip',
  },
  network_partition_asn: {
    cls: 'verdict-badge--asn',
    labelKey: 'incidents.verdict_short_partition_asn',
    explainKey: 'incidents.verdict_partition_asn_tip',
  },
  network_partition_geo: {
    cls: 'verdict-badge--geo',
    labelKey: 'incidents.verdict_short_partition_geo',
    explainKey: 'incidents.verdict_partition_geo_tip',
  },
  inconclusive: {
    cls: 'verdict-badge--inconclusive',
    labelKey: 'incidents.verdict_short_inconclusive',
    explainKey: 'incidents.verdict_inconclusive_tip',
  },
}

// Returns { cls, labelKey, explainKey } for a known verdict, or null for a
// null/unknown one (the majority of historical incidents — computed before
// V2-02-02, or never classified).
export function verdictInfo(verdict) {
  return VERDICT_INFO[verdict] ?? null
}
