import { defineConfig } from 'tsdown'

export default defineConfig({
  entry: [
    'build-temp/index.js',
    'build-temp/init-command.js',
    'build-temp/driver.js',
  ],
  outDir: 'lib',
  format: ['esm'],
  platform: 'node',
  target: 'es2024',
  fixedExtension: false,
  dts: false,
  clean: false,
  sourcemap: false,
})
