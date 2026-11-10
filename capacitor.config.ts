import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.sumpath.nctoollist',
  appName: 'Sum Path',
  webDir: 'dist',
  android: {
    // 사내 테스트용 debug APK: 크롬 원격 디버깅(chrome://inspect) 허용
    webContentsDebuggingEnabled: true,
  },
};

export default config;
