import React, { useEffect, useState } from 'react';

interface Campaign {
  id: string;
  campaign_name: string;
  status: string;
  target_audience: string;
  theme: string;
  created_at: string;
  preview_url?: string;
  production_url?: string;
}

const statusColors: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-800',
  generating: 'bg-blue-100 text-blue-800',
  preview_ready: 'bg-yellow-100 text-yellow-800',
  email_ready: 'bg-purple-100 text-purple-800',
  approved: 'bg-indigo-100 text-indigo-800',
  live: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800'
};

const statusLabels: Record<string, string> = {
  draft: 'Draft',
  generating: 'Generating...',
  preview_ready: 'Preview Ready',
  email_ready: 'Email Ready',
  approved: 'Approved',
  live: 'Live',
  failed: 'Failed'
};

export default function Dashboard() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCampaigns();
  }, []);

  const fetchCampaigns = async () => {
    try {
      const response = await fetch('/api/campaigns');
      if (!response.ok) throw new Error('Failed to fetch campaigns');
      const data = await response.json();
      setCampaigns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-800">Error: {error}</p>
        <button 
          onClick={fetchCampaigns}
          className="mt-2 text-red-600 underline"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Campaign Dashboard</h1>
        <p className="mt-2 text-gray-600">Manage your marketing campaigns</p>
      </div>

      {campaigns.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
          </svg>
          <h3 className="mt-2 text-lg font-medium text-gray-900">No campaigns yet</h3>
          <p className="mt-1 text-gray-500">Get started by creating a new campaign.</p>
          <div className="mt-6">
            <a
              href="/create"
              className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-secondary bg-primary hover:bg-yellow-500"
            >
              Create Campaign
            </a>
          </div>
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {campaigns.map((campaign) => (
            <div key={campaign.id} className="bg-white rounded-lg shadow-md overflow-hidden hover:shadow-lg transition-shadow">
              <div className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <span className={`px-2 py-1 text-xs font-medium rounded-full ${statusColors[campaign.status] || statusColors.draft}`}>
                    {statusLabels[campaign.status] || campaign.status}
                  </span>
                  <span className="text-xs text-gray-500">
                    {new Date(campaign.created_at).toLocaleDateString()}
                  </span>
                </div>
                
                <h3 className="text-lg font-semibold text-gray-900 mb-2">
                  {campaign.campaign_name}
                </h3>
                
                <p className="text-sm text-gray-600 mb-4">
                  Target: {campaign.target_audience}
                </p>
                
                <div className="flex space-x-2">
                  {campaign.preview_url && (
                    <a
                      href={campaign.preview_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-blue-600 hover:text-blue-800"
                    >
                      Preview →
                    </a>
                  )}
                  {campaign.production_url && (
                    <a
                      href={campaign.production_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-green-600 hover:text-green-800"
                    >
                      Live Site →
                    </a>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
