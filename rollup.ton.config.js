import resolve from '@rollup/plugin-node-resolve';
import { terser } from 'rollup-plugin-terser';

export default [
  {
    input: 'node_modules/@ton/core/dist/index.js',
    output: {
      file: 'public/ton-core-umd.js',
      format: 'umd',
      name: 'TONCore',
    },
    plugins: [resolve(), terser()],
  },
  {
    input: 'node_modules/ton/dist/index.js',
    output: {
      file: 'public/ton-umd.js',
      format: 'umd',
      name: 'TON',
    },
    plugins: [resolve(), terser()],
  },
];
