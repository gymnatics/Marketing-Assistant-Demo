import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import WorkflowNavigator from '../components/WorkflowNavigator/WorkflowNavigator';
import CampaignWizard from '../components/CampaignWizard/CampaignWizard';
import PreviewPanel from '../components/PreviewPanel/PreviewPanel';

export interface CampaignData {
  campaign_name: string;
  campaign_description: string;
  hotel_name: string;
  target_audience: string;
  theme: string;
  start_date: string;
  end_date: string;
}

export interface CampaignState {
  id?: string;
  status: string;
  preview_url?: string;
  production_url?: string;
  email_subject_en?: string;
  email_body_en?: string;
  email_subject_zh?: string;
  email_body_zh?: string;
  customer_count?: number;
  error?: string;
}

const STEPS = [
  { id: 'details', name: 'Campaign Details', description: 'Basic information' },
  { id: 'theme', name: 'Select Theme', description: 'Visual style' },
  { id: 'landing', name: 'Landing Page', description: 'Preview & edit' },
  { id: 'email', name: 'Email Preview', description: 'Recipients & content' },
  { id: 'confirm', name: 'Confirmation', description: 'Review & go live' },
  { id: 'success', name: 'Success', description: 'Campaign live' }
];

export default function CampaignCreate() {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(0);
  const [campaignData, setCampaignData] = useState<CampaignData>({
    campaign_name: '',
    campaign_description: '',
    hotel_name: 'Grand Lisboa Palace',
    target_audience: '',
    theme: 'luxury_gold',
    start_date: '',
    end_date: ''
  });
  const [campaignState, setCampaignState] = useState<CampaignState>({
    status: 'draft'
  });
  const [loading, setLoading] = useState(false);
  const [agentStatus, setAgentStatus] = useState<string>('');

  const handleDataChange = (data: Partial<CampaignData>) => {
    setCampaignData(prev => ({ ...prev, ...data }));
  };

  const createCampaign = async () => {
    setLoading(true);
    setAgentStatus('Creating campaign...');
    
    try {
      const response = await fetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(campaignData)
      });
      
      if (!response.ok) throw new Error('Failed to create campaign');
      
      const result = await response.json();
      setCampaignState(prev => ({ ...prev, id: result.campaign_id, status: 'draft' }));
      return result.campaign_id;
    } catch (err) {
      setCampaignState(prev => ({ 
        ...prev, 
        error: err instanceof Error ? err.message : 'Unknown error' 
      }));
      throw err;
    } finally {
      setLoading(false);
      setAgentStatus('');
    }
  };

  const generateLandingPage = async (campaignId: string) => {
    setLoading(true);
    setAgentStatus('Creative Producer: Generating landing page...');
    
    try {
      const response = await fetch(`/api/campaigns/${campaignId}/generate`, {
        method: 'POST'
      });
      
      if (!response.ok) throw new Error('Failed to generate landing page');
      
      const result = await response.json();
      setCampaignState(prev => ({ 
        ...prev, 
        status: result.status,
        preview_url: result.preview_url,
        error: result.error
      }));
      
      if (result.status === 'preview_ready') {
        setCurrentStep(2);
      }
    } catch (err) {
      setCampaignState(prev => ({ 
        ...prev, 
        error: err instanceof Error ? err.message : 'Unknown error' 
      }));
    } finally {
      setLoading(false);
      setAgentStatus('');
    }
  };

  const prepareEmailPreview = async () => {
    if (!campaignState.id) return;
    
    setLoading(true);
    setAgentStatus('Customer Analyst: Retrieving customers...');
    
    try {
      const response = await fetch(`/api/campaigns/${campaignState.id}/preview-email`, {
        method: 'POST'
      });
      
      if (!response.ok) throw new Error('Failed to prepare email preview');
      
      const result = await response.json();
      
      setAgentStatus('Delivery Manager: Generating email content...');
      
      const campaignResponse = await fetch(`/api/campaigns/${campaignState.id}`);
      const campaignDetails = await campaignResponse.json();
      
      setCampaignState(prev => ({ 
        ...prev, 
        status: result.status,
        customer_count: result.customer_count,
        email_subject_en: campaignDetails.email_subject_en,
        email_body_en: campaignDetails.email_body_en,
        email_subject_zh: campaignDetails.email_subject_zh,
        email_body_zh: campaignDetails.email_body_zh,
        error: result.error
      }));
      
      if (result.status === 'email_ready') {
        setCurrentStep(3);
      }
    } catch (err) {
      setCampaignState(prev => ({ 
        ...prev, 
        error: err instanceof Error ? err.message : 'Unknown error' 
      }));
    } finally {
      setLoading(false);
      setAgentStatus('');
    }
  };

  const goLive = async () => {
    if (!campaignState.id) return;
    
    setLoading(true);
    setAgentStatus('Delivery Manager: Deploying to production...');
    
    try {
      const response = await fetch(`/api/campaigns/${campaignState.id}/approve`, {
        method: 'POST'
      });
      
      if (!response.ok) throw new Error('Failed to go live');
      
      const result = await response.json();
      setCampaignState(prev => ({ 
        ...prev, 
        status: result.status,
        production_url: result.production_url,
        error: result.error
      }));
      
      if (result.status === 'live') {
        setCurrentStep(5);
      }
    } catch (err) {
      setCampaignState(prev => ({ 
        ...prev, 
        error: err instanceof Error ? err.message : 'Unknown error' 
      }));
    } finally {
      setLoading(false);
      setAgentStatus('');
    }
  };

  const handleNext = async () => {
    if (currentStep === 0) {
      setCurrentStep(1);
    } else if (currentStep === 1) {
      try {
        const campaignId = await createCampaign();
        await generateLandingPage(campaignId);
      } catch (err) {
        console.error('Error:', err);
      }
    } else if (currentStep === 2) {
      await prepareEmailPreview();
    } else if (currentStep === 3) {
      setCurrentStep(4);
    } else if (currentStep === 4) {
      await goLive();
    }
  };

  const handleBack = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2">
        <div className="bg-white rounded-lg shadow-md p-6">
          <WorkflowNavigator steps={STEPS} currentStep={currentStep} />
          
          {agentStatus && (
            <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-center">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mr-3"></div>
              <span className="text-blue-800 text-sm">{agentStatus}</span>
            </div>
          )}
          
          {campaignState.error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <span className="text-red-800 text-sm">Error: {campaignState.error}</span>
            </div>
          )}
          
          <div className="mt-6">
            <CampaignWizard
              step={STEPS[currentStep].id}
              data={campaignData}
              state={campaignState}
              onChange={handleDataChange}
              onNext={handleNext}
              onBack={handleBack}
              loading={loading}
            />
          </div>
        </div>
      </div>
      
      <div className="lg:col-span-1">
        <PreviewPanel
          step={STEPS[currentStep].id}
          data={campaignData}
          state={campaignState}
        />
      </div>
    </div>
  );
}
