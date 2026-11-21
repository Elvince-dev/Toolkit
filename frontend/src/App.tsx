import { useState, useEffect } from 'react';
import ChatPage from './components/ChatPage';
import WelcomeScreen from './components/WelcomeScreen';

function App() {
  const [activeDataset, setActiveDataset] = useState<string | null>(() =>
    localStorage.getItem("toolkit_active_dataset")?.replace(/\.csv$/i, "") || null,
  );
  const [showWelcome, setShowWelcome] = useState(() => !localStorage.getItem("toolkit_active_dataset"));

  useEffect(() => {
    if (activeDataset) {
      localStorage.setItem("toolkit_active_dataset", activeDataset);
    } else {
      localStorage.removeItem("toolkit_active_dataset");
    }
  }, [activeDataset]);

  const handleUploadSuccess = (filename: string) => {
    setActiveDataset(filename);
    setShowWelcome(false);
  };

  if (showWelcome || !activeDataset) {
    return (
      <WelcomeScreen
        onUploadSuccess={handleUploadSuccess}
        onCancel={activeDataset ? () => setShowWelcome(false) : undefined}
      />
    );
  }

  return (
    <ChatPage
      datasetName={activeDataset}
      onAddDataset={() => setShowWelcome(true)}
    />
  );
}

export default App;