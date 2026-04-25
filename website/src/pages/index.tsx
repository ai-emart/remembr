import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import styles from './index.module.css';

const features = [
  {
    title: 'Quick Start',
    icon: '⚡',
    description: 'Add persistent memory to your agent in under 5 minutes.',
    link: '/remembr/docs/quickstart/langchain',
  },
  {
    title: '8 Framework Adapters',
    icon: '🔌',
    description:
      'Native adapters for LangChain, LangGraph, CrewAI, AutoGen, LlamaIndex, Pydantic AI, OpenAI Agents, and Haystack.',
    link: '/remembr/docs/quickstart/langchain',
  },
  {
    title: 'API Reference',
    icon: '📖',
    description: 'Every endpoint, every parameter, every response shape documented.',
    link: '/remembr/docs/api-reference',
  },
  {
    title: 'Self-Hosting',
    icon: '🐳',
    description: 'One command. No API keys required. Runs fully local with Ollama embeddings.',
    link: '/remembr/docs/self-hosted',
  },
  {
    title: 'Hybrid Search',
    icon: '🔍',
    description: 'Semantic + BM25 + recency scoring with configurable weights.',
    link: '/remembr/docs/concepts/search-modes',
  },
  {
    title: 'GDPR Compliant',
    icon: '🛡️',
    description:
      'Soft deletes, hard deletes, export, and targeted erasure at every scope level.',
    link: '/remembr/docs/cookbook/gdpr-deletion',
  },
];

export default function Home() {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout title={siteConfig.title} description={siteConfig.tagline}>
      <main>
        {/* Hero */}
        <div className={styles.hero}>
          <h1 className={styles.heroTitle}>Remembr</h1>
          <p className={styles.heroSubtitle}>
            Persistent memory infrastructure for AI agents.
            <br />
            Store, search, and delete memories across sessions — with one command to self-host.
          </p>
          <div className={styles.heroCtas}>
            <Link className={styles.ctaPrimary} to="/remembr/docs/quickstart/langchain">
              Get Started →
            </Link>
            <Link className={styles.ctaSecondary} to="https://github.com/ai-emart/remembr">
              View on GitHub
            </Link>
          </div>
          <div className={styles.heroInstall}>
            <code>pip install remembr</code>
            <span className={styles.separator}>·</span>
            <code>npm install @remembr/sdk</code>
          </div>
        </div>

        {/* Feature cards */}
        <div className={styles.features}>
          <div className={styles.grid}>
            {features.map((f) => (
              <Link key={f.title} to={f.link} className={styles.card}>
                <div className={styles.cardIcon}>{f.icon}</div>
                <h3 className={styles.cardTitle}>{f.title}</h3>
                <p className={styles.cardDesc}>{f.description}</p>
              </Link>
            ))}
          </div>
        </div>

        {/* Code example */}
        <div className={styles.codeSection}>
          <h2>Dead simple API</h2>
          <pre className={styles.codeBlock}>{`from remembr import RemembrClient

async with RemembrClient(api_key="...", base_url="http://localhost:8000/api/v1") as client:
    session = await client.create_session(metadata={"user": "alice"})

    await client.store(
        "Alice prefers weekly billing summaries on Fridays.",
        role="user",
        session_id=session.session_id,
        tags=["kind:preference", "topic:billing"],
    )

    results = await client.search(
        "When should billing summaries be sent?",
        session_id=session.session_id,
        search_mode="hybrid",
    )
    print(results.results[0].content)`}</pre>
        </div>
      </main>
    </Layout>
  );
}
