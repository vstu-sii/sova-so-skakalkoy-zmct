/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const extractor = process.env.EXTRACTOR_URL || 'http://extractor:8000'
    const composer = process.env.COMPOSER_URL || 'http://page-composer:8000'
    const publisher = process.env.PUBLISHER_URL || 'http://vk-publisher:8000'
    const mailer = process.env.MAILER_URL || 'http://mailer:8000'
    return [
      { source: '/api/extractor/:path*', destination: `${extractor}/:path*` },
      { source: '/api/composer/:path*', destination: `${composer}/:path*` },
      { source: '/api/vk-publisher/:path*', destination: `${publisher}/:path*` },
      { source: '/api/mailer/:path*', destination: `${mailer}/:path*` },
    ]
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
