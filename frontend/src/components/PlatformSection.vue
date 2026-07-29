<template>
  <section id="platforms" class="py-16 sm:py-20 bg-bg-section" aria-labelledby="platforms-heading">
    <div class="max-w-6xl mx-auto px-4 sm:px-6">
      <div class="text-center mb-12">
        <h2 id="platforms-heading" class="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
          {{ t('platforms.title') }}
        </h2>
        <p class="text-text-secondary text-base max-w-xl mx-auto">
          {{ t('platforms.desc') }}
        </p>
      </div>

      <div class="grid gap-4 sm:grid-cols-3">
        <div
          v-for="group in platformGroups"
          :key="group.titleKey"
          class="bg-white border border-border-light rounded-xl p-4 shadow-sm"
        >
          <div class="flex items-center gap-2 mb-3">
            <span class="w-8 h-8 rounded-lg bg-primary-light text-primary flex items-center justify-center text-sm font-semibold">
              {{ group.mark }}
            </span>
            <h3 class="text-sm font-semibold text-text-primary">{{ t(group.titleKey) }}</h3>
          </div>
          <div class="flex flex-wrap gap-2">
            <span
              v-for="platform in group.platforms"
              :key="platform"
              class="inline-flex items-center px-2.5 py-1 rounded-full bg-bg-section text-xs font-medium text-text-secondary border border-border-light"
            >
              {{ platform }}
            </span>
          </div>
        </div>
      </div>

      <p class="text-center mt-8 text-sm text-text-muted">
        {{ t('platforms.more') }}
      </p>
    </div>
  </section>
</template>

<script setup>
import { useI18n } from '../i18n.js'

const { t } = useI18n()

const platformGroups = [
  {
    mark: 'V',
    titleKey: 'platforms.video',
    platforms: [
      'YouTube', 'Bilibili', '抖音', '快手', '爱奇艺', '优酷',
      '芒果TV', '腾讯视频', 'TikTok', 'Vimeo', 'Dailymotion', 'Twitch',
    ],
  },
  {
    mark: 'A',
    titleKey: 'platforms.audio',
    platforms: ['SoundCloud', 'Bandcamp', 'Mixcloud', 'Audiomack', 'Podcast', 'YouTube Music'],
  },
  {
    mark: 'S',
    titleKey: 'platforms.social',
    platforms: ['Instagram', 'Facebook', 'X / Twitter', 'Reddit', 'Pinterest', 'Tumblr', '微博'],
  },
]
</script>
