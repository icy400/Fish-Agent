<template>
  <div class="app-bg">
    <el-menu mode="horizontal" router class="main-menu">
      <el-menu-item index="/audio-analysis">音 频 分 析</el-menu-item>
      <el-menu-item index="/realtime">实 时 监 测</el-menu-item>
    </el-menu>
    <router-view />
  </div>
</template>

<style scoped>
.app-bg {
  min-height: 100vh;
  background: linear-gradient(120deg, #e0f7fa 0%, #f0f9ff 50%, #fef6fb 100%);
}

.main-menu {
  border-radius: 0 0 18px 18px;
  margin: 0 auto 24px auto;
  box-shadow: 0 4px 24px 0 rgba(0, 160, 255, 0.08), 0 1.5px 6px 0 rgba(0, 0, 0, 0.04);
  background: linear-gradient(90deg, #a5f3fc 100%, #a5f3fc 100%);
  padding: 0 40px;
  width: 100vw;
  font-size: 18px;
  display: flex;
}

.el-menu-item {
  color: #0284c7;
  font-weight: 600;
  font-size: 18px;
  margin: 0 8px;
  transition: background 0.2s, color 0.2s;
}

.el-menu-item.is-active,
.el-menu-item:hover {
  background: #ffffffa1 !important;
  border-bottom: 3px solid #ffffffa1 !important;
}
</style>