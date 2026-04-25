import { themes as prismThemes } from 'prism-react-renderer';
import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Remembr',
  tagline: 'Persistent memory infrastructure for AI agents',
  favicon: 'img/favicon.ico',

  url: 'https://ai-emart.github.io',
  baseUrl: '/remembr/',
  organizationName: 'ai-emart',
  projectName: 'remembr',
  trailingSlash: false,

  onBrokenLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/ai-emart/remembr/edit/main/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/logo.png',
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Remembr',
      logo: {
        alt: 'Remembr Logo',
        src: 'img/logo.png',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          label: 'Docs',
          position: 'left',
        },
        {
          to: '/docs/api-reference',
          label: 'API',
          position: 'left',
        },
        {
          href: 'https://github.com/ai-emart/remembr',
          label: 'GitHub',
          position: 'right',
        },
        {
          href: 'https://pypi.org/project/remembr/',
          label: 'PyPI',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            { label: 'Quick Start', to: '/docs/quickstart/langchain' },
            { label: 'API Reference', to: '/docs/api-reference' },
            { label: 'Self-Hosting', to: '/docs/self-hosted' },
          ],
        },
        {
          title: 'Community',
          items: [
            { label: 'GitHub', href: 'https://github.com/ai-emart/remembr' },
            { label: 'PyPI', href: 'https://pypi.org/project/remembr/' },
            { label: 'npm', href: 'https://www.npmjs.com/package/@remembr/sdk' },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Emmanuel Nwanguma. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['python', 'typescript', 'bash', 'toml', 'yaml', 'docker'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
