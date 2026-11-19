import { useState, useEffect } from 'react';
import ChatPage from './components/ChatPage';
import WelcomeScreen from './components/WelcomeScreen';

function App() {
  const [hasDataset, setHasDataset] = useState<boolean>(false);

  // Check if we have a dataset in local storage on mount
  useEffect(() => {
    const activeDataset = localStorage.getItem("toolkit_active_dataset");
    if (activeDataset) setHasDataset(true);
  }, []);

  const handleUploadSuccess = (filename: string) => {
    localStorage.setItem("toolkit_active_dataset", filename);
    setHasDataset(true);
  };

  if (!hasDataset) {
    return <WelcomeScreen onUploadSuccess={handleUploadSuccess} />;
  }

  return <ChatPage />;
}

export default App;