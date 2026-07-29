<template>
  <section id="comparison" class="py-16 sm:py-20 bg-bg-section" aria-labelledby="comparison-heading">
    <div class="max-w-5xl mx-auto px-4 sm:px-6">
      <div class="text-center mb-12">
        <h2 id="comparison-heading" class="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
          {{ t('comparison.title') }}
        </h2>
        <p class="text-text-secondary text-base max-w-xl mx-auto">
          {{ t('comparison.desc') }}
        </p>
      </div>

      <div class="overflow-x-auto rounded-2xl border border-border-light shadow-sm">
        <table class="w-full text-sm">
          <thead>
            <tr class="bg-gray-50 text-text-primary">
              <th class="text-left px-5 py-3.5 font-semibold">{{ columns[0] }}</th>
              <th class="px-5 py-3.5 font-semibold text-primary">{{ columns[1] }}</th>
              <th class="px-5 py-3.5 font-semibold">{{ columns[2] }}</th>
              <th class="px-5 py-3.5 font-semibold">{{ columns[3] }}</th>
            </tr>
          </thead>
          <tbody class="bg-white">
            <tr v-for="(row, i) in rows" :key="row.feature" :class="i % 2 === 1 ? 'bg-gray-50/50' : ''">
              <td class="px-5 py-3 text-text-primary font-medium">{{ row.feature }}</td>
              <td class="px-5 py-3 text-center">
                <span v-if="row.saveany === true" class="text-success text-base">✓</span>
                <span v-else-if="row.saveany === false" class="text-text-muted">✗</span>
                <span v-else class="text-text-primary">{{ row.saveany }}</span>
              </td>
              <td class="px-5 py-3 text-center text-text-secondary">
                <span v-if="row.online === true" class="text-success text-base">✓</span>
                <span v-else-if="row.online === false" class="text-text-muted">✗</span>
                <span v-else>{{ row.online }}</span>
              </td>
              <td class="px-5 py-3 text-center text-text-secondary">
                <span v-if="row.desktop === true" class="text-success text-base">✓</span>
                <span v-else-if="row.desktop === false" class="text-text-muted">✗</span>
                <span v-else>{{ row.desktop }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../i18n.js'

const { t } = useI18n()

const columns = computed(() => t('comparison.columns'))
const rows = computed(() => t('comparison.rows').map(([feature, saveany, online, desktop]) => ({
  feature,
  saveany,
  online,
  desktop,
})))
</script>
