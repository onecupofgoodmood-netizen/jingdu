<template>
  <footer class="bg-white border-t border-border-light py-8">
    <div class="max-w-6xl mx-auto px-4 sm:px-6">
      <!-- 底部关键词友好描述 -->
      <div class="text-center mb-6">
        <p class="text-sm text-text-secondary leading-relaxed max-w-3xl mx-auto">
          <strong>{{ t('common.brand') }}</strong> — {{ t('footer.desc') }}
        </p>
      </div>
      <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
        <a href="/" class="flex items-center gap-2" :title="t('footer.home')">
          <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center">
            <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <span class="text-sm font-medium text-text-primary">{{ t('common.brand') }}</span>
        </a>
        <p class="text-xs text-text-muted text-center leading-relaxed">
          {{ t('footer.disclaimer') }}
        </p>
        <p class="text-xs text-text-muted">
          &copy; {{ new Date().getFullYear() }} {{ t('common.brand') }}
        </p>
      </div>
    </div>
  </footer>
</template>

<script setup>
import { useI18n } from '../i18n.js'

const { t } = useI18n()
</script>
