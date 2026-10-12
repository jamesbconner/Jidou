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
      // Complexity ratchet (frontend simplification plan, Task 1): pinned at
      // the measured maximum (ShowDetail = 77 after the FE-3 Settings split).
      // It may only ever be lowered.
      complexity: ['error', 77],
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
    // Hooks boundary (frontend simplification plan, Task 4): pages and
    // components consume data through `@/hooks/*`; they never call the API
    // client or the query client themselves, so cache keys and invalidation
    // stay in one layer.
    files: ['src/pages/**/*.{ts,tsx}', 'src/components/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '@/api/client',
              message: 'Pages and components must go through a hook in src/hooks/ instead of calling the API client.',
            },
          ],
          // Also catch relative spellings such as '../api/client'.
          patterns: [
            {
              group: ['**/api/client'],
              message: 'Pages and components must go through a hook in src/hooks/ instead of calling the API client.',
            },
          ],
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.name='useQueryClient']",
          message: 'Pages and components must not use the query client; put the cache logic in a hook in src/hooks/.',
        },
      ],
    },
  },
  {
    // Test bodies are long linear scripts; the ratchet targets production code.
    files: ['src/tests/**'],
    rules: { complexity: 'off' },
  },
  {
    ignores: ['dist/**', 'node_modules/**', 'src/types/api-generated.ts'],
  },
]
