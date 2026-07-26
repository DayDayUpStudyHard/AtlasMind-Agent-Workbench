<template>
  <footer class="footer">
    <div class="footer-inner">
      <div class="footer-divider"></div>
      <div class="footer-bottom">
        <span>&copy; 2024 AtlasMind</span>
        <span class="separator">·</span>
        <span>Powered by Spring Boot & Vue</span>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.footer { padding: 40px 0 28px; }
.footer-inner { max-width: 860px; margin: 0 auto; padding: 0 20px; }

.footer-divider {
  height: 1px; margin-bottom: 20px;
  background: var(--atlas-border);
}

.footer-bottom {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  font-size: 13px; color: var(--atlas-muted);
}
.separator { color: var(--atlas-border-strong); }
</style>
