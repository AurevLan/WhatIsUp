<template>
  <span class="badge" :class="enabled ? 'badge-up' : 'badge-unknown'">
    <slot>{{ label }}</slot>
  </span>
</template>

<script setup>
// Small shared "enabled/disabled" pill — chantier ergonomie, item 8.
//
// Three call sites (OnCallView ×2, DiscoveryView ×1) each reimplemented this
// locally; one of them (OnCallView) even dropped the base `.badge` class and
// kept only the color modifier, so its pill was missing the shared padding /
// border / uppercase treatment entirely — a real visual drift, not just
// duplicated markup.
//
// The label is a prop (or a slot), not an i18n key owned by this component:
// "enabled"/"disabled" agrees in gender with whatever noun it qualifies
// ("rotation désactivée" vs "politique désactivée" vs generic "Désactivé"
// in French), so only the caller — which knows that noun — can pick the
// grammatically correct string. This component only owns the visual mapping
// from a boolean to the right badge class.
defineProps({
  enabled: { type: Boolean, default: false },
  label: { type: String, default: '' },
})
</script>
