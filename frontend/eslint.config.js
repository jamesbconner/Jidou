import js from '@eslint/js'
import tseslint from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default [
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    plugins: {
      '@typescript-eslint': tseslint,
      react,
      'react-hooks': reactHooks,
    },
    settings: {
      react: { version: 'detect' },
    },
    rules: {
      ...tseslint.configs.recommended.rules,
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'warn',
      // TypeScript's own compiler is authoritative for undefined-symbol
      // detection (ambient types, JSX namespace, etc.) — no-undef produces
      // false positives on TS-only constructs that tsc already catches.
      'no-undef': 'off',
    },
  },
  {
    files: ['**/tests/**/*.{ts,tsx}'],
    rules: {
      // Test-only wrapper components (renderHook's `wrapper` option, etc.)
      // are never rendered outside the test itself — no debugging value
      // from a displayName.
      'react/display-name': 'off',
    },
  },
  {
    ignores: ['dist/**', 'node_modules/**', 'src/types/api-generated.ts'],
  },
]
