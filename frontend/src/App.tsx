import { useState, useEffect } from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from './supabaseClient';
import { apiErrorMessage, authenticatedFetch } from './api';
import ChatPage from './components/ChatPage';
import WelcomeScreen from './components/WelcomeScreen';
import SignInPage from './components/SignInPage';
import type { Dataset } from './types';

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState(true);
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);
  const [isResettingPassword, setIsResettingPassword] = useState(false);
  const [authMessage, setAuthMessage] = useState('');
  const [authError, setAuthError] = useState('');
  const [datasetState, setDatasetState] = useState<{ userId: string; datasets: Dataset[] }>({
    userId: '',
    datasets: [],
  });
  const [selectedDatasetState, setSelectedDatasetState] = useState<{
    userId: string;
    dataset: Dataset;
  } | null>(null);
  const [datasetError, setDatasetError] = useState('');
  const userId = session?.user.id;
  const datasets = datasetState.userId === userId ? datasetState.datasets : [];
  const isLoadingDatasets = Boolean(userId && datasetState.userId !== userId);
  const selectedDataset =
    selectedDatasetState && selectedDatasetState.userId === userId
      ? selectedDatasetState.dataset
      : null;

  useEffect(() => {
    let active = true;
    supabase.auth.getSession()
      .then(({ data, error }) => {
        if (!active) return;
        if (error) setAuthError(error.message);
        setSession(data.session);
        setIsLoadingSession(false);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setAuthError(cause instanceof Error ? cause.message : 'Unable to load your session.');
        setIsLoadingSession(false);
      });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      setSession(session);
      if (event === 'PASSWORD_RECOVERY') setIsResettingPassword(true);
      if (event === 'SIGNED_OUT') setIsResettingPassword(false);
      setIsLoadingSession(false);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!userId) return;

    const controller = new AbortController();
    let active = true;
    authenticatedFetch('/api/datasets', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(await apiErrorMessage(response));
        return response.json() as Promise<{ datasets: Dataset[] }>;
      })
      .then(({ datasets }) => {
        if (active) {
          setDatasetState({ userId, datasets });
          setDatasetError('');
        }
      })
      .catch((cause: unknown) => {
        if (active && !(cause instanceof DOMException && cause.name === 'AbortError')) {
          setDatasetState({ userId, datasets: [] });
          setDatasetError(cause instanceof Error ? cause.message : 'Unable to load your datasets.');
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [userId]);

  const handleSignIn = async (email: string, password: string) => {
    setIsSubmittingAuth(true);
    setAuthError('');
    setAuthMessage('');
    try {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : 'Unable to sign in.');
    } finally {
      setIsSubmittingAuth(false);
    }
  };

  const handleSignUp = async (email: string, password: string) => {
    setIsSubmittingAuth(true);
    setAuthError('');
    setAuthMessage('');
    try {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: window.location.origin },
      });
      if (error) throw error;
      setAuthMessage(
        data.session
          ? 'Your account is ready.'
          : 'Check your email once to confirm your account, then sign in with your password.',
      );
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : 'Unable to create your account.');
    } finally {
      setIsSubmittingAuth(false);
    }
  };

  const handlePasswordResetRequest = async (email: string) => {
    setIsSubmittingAuth(true);
    setAuthError('');
    setAuthMessage('');
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: window.location.origin,
      });
      if (error) throw error;
      setAuthMessage('If an account exists for that email, a password reset link is on its way.');
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : 'Unable to request a password reset.');
    } finally {
      setIsSubmittingAuth(false);
    }
  };

  const handlePasswordUpdate = async (password: string) => {
    setIsSubmittingAuth(true);
    setAuthError('');
    setAuthMessage('');
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      setIsResettingPassword(false);
      setAuthMessage('Your password has been updated.');
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : 'Unable to update your password.');
    } finally {
      setIsSubmittingAuth(false);
    }
  };

  const handleSignOut = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) {
      setAuthError(error.message);
      return;
    }
    setDatasetState({ userId: '', datasets: [] });
    setSelectedDatasetState(null);
    setIsResettingPassword(false);
    setAuthError('');
  };

  if (isLoadingSession) {
    return <div className="min-h-screen flex items-center justify-center bg-background text-muted">Loading Toolkit...</div>;
  }

  if (isResettingPassword) {
    return (
      <SignInPage
        isSubmitting={isSubmittingAuth}
        isResettingPassword={isResettingPassword}
        message={authMessage}
        error={authError}
        onSignIn={handleSignIn}
        onSignUp={handleSignUp}
        onRequestPasswordReset={handlePasswordResetRequest}
        onSetPassword={handlePasswordUpdate}
      />
    );
  }

  if (!session) {
    return (
      <SignInPage
        isSubmitting={isSubmittingAuth}
        isResettingPassword={isResettingPassword}
        message={authMessage}
        error={authError}
        onSignIn={handleSignIn}
        onSignUp={handleSignUp}
        onRequestPasswordReset={handlePasswordResetRequest}
        onSetPassword={handlePasswordUpdate}
      />
    );
  }

  if (isLoadingDatasets) {
    return <div className="min-h-screen flex items-center justify-center bg-background text-muted">Loading your workspace...</div>;
  }

  if (!selectedDataset) {
    return (
      <WelcomeScreen
        datasets={datasets}
        error={datasetError}
        email={session.user.email ?? ''}
        onSelectDataset={(dataset) =>
          setSelectedDatasetState({ userId: session.user.id, dataset })
        }
        onUploadSuccess={(dataset) => {
          setDatasetState((current) => ({
            userId: session.user.id,
            datasets: [
              dataset,
              ...(current.userId === session.user.id ? current.datasets : []),
            ],
          }));
          setSelectedDatasetState({ userId: session.user.id, dataset });
        }}
        onSignOut={handleSignOut}
      />
    );
  }

  return (
    <ChatPage
      key={selectedDataset.id}
      dataset={selectedDataset}
      datasets={datasets}
      email={session.user.email ?? ''}
      onAddDataset={() => setSelectedDatasetState(null)}
      onSelectDataset={(dataset) =>
        setSelectedDatasetState({ userId: session.user.id, dataset })
      }
      onSignOut={handleSignOut}
    />
  );
}

export default App;