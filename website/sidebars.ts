import type { SidebarsConfig } from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    'index',
    {
      type: 'category',
      label: 'Quickstart',
      collapsed: false,
      items: [
        'quickstart/langchain',
        'quickstart/langgraph',
        'quickstart/crewai',
        'quickstart/autogen',
        'quickstart/llamaindex',
        'quickstart/pydantic-ai',
        'quickstart/openai-agents',
        'quickstart/haystack',
      ],
    },
    {
      type: 'category',
      label: 'Concepts',
      items: [
        'concepts/sessions',
        'concepts/episodes',
        'concepts/scoping',
        'concepts/short-term-memory',
        'concepts/search-modes',
        'concepts/embeddings',
        'concepts/soft-deletes',
      ],
    },
    'api-reference',
    {
      type: 'category',
      label: 'Deployment',
      items: [
        'deployment/docker',
        'deployment/railway',
        'deployment/render',
        'deployment/fly',
        'deployment/kubernetes',
      ],
    },
    {
      type: 'category',
      label: 'Operations',
      items: ['security', 'observability', 'admin-ui', 'cli', 'self-hosted'],
    },
    {
      type: 'category',
      label: 'Cookbook',
      items: [
        'cookbook/customer-support-agent',
        'cookbook/coding-assistant',
        'cookbook/gdpr-deletion',
        'cookbook/multi-agent-shared-memory',
        'cookbook/debugging-with-memory-diff',
      ],
    },
    'roadmap',
    'contributing',
  ],
};

export default sidebars;
