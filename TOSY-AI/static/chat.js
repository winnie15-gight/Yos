const box = document.getElementById('messages');
const input = document.getElementById('prompt');
const send = document.getElementById('send');
const statusLine = document.getElementById('ui-status');
const fileInput = document.getElementById('file');
const record = document.getElementById('record');

function showStatus(message, kind = 'info') {
  if (!statusLine) return;
  statusLine.textContent = message;
  statusLine.className = `ui-status visible ${kind}`;
}
function clearStatus() {
  if (!statusLine) return;
  statusLine.textContent = '';
  statusLine.className = 'ui-status';
}
function speakText(text, button) {
  if (!('speechSynthesis' in window)) {
    showStatus('Read-aloud is not supported by this browser.', 'info');
    return;
  }
  if (window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
    document.querySelectorAll('.speak-button').forEach(item => item.classList.remove('speaking'));
    if (button.dataset.wasSpeaking === 'true') {
      button.dataset.wasSpeaking = 'false';
      return;
    }
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = document.documentElement.lang || 'en-US';
  utterance.rate = 1;
  utterance.onstart = () => button.classList.add('speaking');
  utterance.onend = utterance.onerror = () => {
    button.classList.remove('speaking');
    button.dataset.wasSpeaking = 'false';
  };
  button.dataset.wasSpeaking = 'true';
  window.speechSynthesis.speak(utterance);
}
function bubble(role, text, extraClass = '') {
  const row = document.createElement('div');
  row.className = `message-row ${role}`;
  const el = document.createElement('div');
  el.className = `bubble ${role} ${extraClass}`.trim();
  el.textContent = text;
  row.appendChild(el);
  if (role === 'assistant' && text && extraClass !== 'thinking') {
    const speak = document.createElement('button');
    speak.type = 'button';
    speak.className = 'speak-button';
    speak.title = 'Read response aloud';
    speak.setAttribute('aria-label', 'Read response aloud');
    speak.textContent = '🔊';
    speak.addEventListener('click', () => speakText(el.textContent, speak));
    row.appendChild(speak);
  }
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
  return el;
}
async function readResponse(response) {
  const type = response.headers.get('content-type') || '';
  if (!type.includes('application/json')) throw new Error('The server returned an unexpected response.');
  return response.json();
}
async function load() {
  try {
    const response = await fetch('/api/history');
    if (!response.ok) throw new Error('History is temporarily unavailable.');
    const data = await readResponse(response);
    if (Array.isArray(data.messages) && data.messages.length) {
      box.innerHTML = '';
      data.messages.forEach(item => bubble(item.role, item.content));
    }
  } catch (error) {
    showStatus('Your chat history could not load just now. You can still start a new message.', 'info');
  }
}
async function submit() {
  const message = input.value.trim();
  if (!message || send.disabled) return;
  input.value = '';
  input.style.height = 'auto';
  const welcome = box.querySelector('.welcome');
  if (welcome) welcome.remove();
  bubble('user', message);
  send.disabled = true;
  send.classList.add('loading');
  clearStatus();
  const waiting = bubble('assistant', 'Thinking…', 'thinking');
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message})
    });
    const data = await readResponse(response);
    if (!response.ok) {
      waiting.textContent = data.error || 'I couldn’t complete that request. Please try again.';
      waiting.classList.add('soft-error');
    } else {
      waiting.textContent = data.reply || 'I don’t have a response right now. Please try again.';
      waiting.classList.remove('thinking');
      const row = waiting.parentElement;
      const speak = document.createElement('button');
      speak.type = 'button'; speak.className = 'speak-button';
      speak.title = 'Read response aloud'; speak.setAttribute('aria-label', 'Read response aloud');
      speak.textContent = '🔊';
      speak.addEventListener('click', () => speakText(waiting.textContent, speak));
      row.appendChild(speak);
    }
  } catch (error) {
    waiting.textContent = 'I can’t reach TOSY right now. Check your connection and try again.';
    waiting.classList.add('soft-error');
  } finally {
    send.disabled = false;
    send.classList.remove('loading');
    input.focus();
    box.scrollTop = box.scrollHeight;
  }
}
send.addEventListener('click', submit);
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    submit();
  }
});
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

fileInput.addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  showStatus('Checking your file…');
  try {
    const isImage = file.type.startsWith('image/');
    if (isImage) {
      bubble('user', `📷 Image uploaded: ${file.name}`);
      const response = await fetch('/api/analyze-image', {method: 'POST', body: form});
      const data = await readResponse(response);
      if (!response.ok) throw new Error(data.error || 'TOSY could not analyze this image.');
      bubble('assistant', data.reply || 'I received the image, but could not produce an analysis.');
      showStatus('Image analyzed successfully.', 'success');
    } else {
      const response = await fetch('/api/upload', {method: 'POST', body: form});
      const data = await readResponse(response);
      showStatus(data.message || data.error || 'The file could not be processed.', response.ok ? 'success' : 'error');
    }
  } catch (error) {
    showStatus(error.message || 'The upload didn’t go through. Please check your connection and try again.', 'error');
  } finally {
    event.target.value = '';
  }
});

// Browser-native speech recognition: spoken words are inserted into the composer.
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = 'en-NG';
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.onstart = () => {
    listening = true;
    record.classList.add('recording');
    record.innerHTML = '■<span>Listening</span>';
    showStatus('Listening… speak now.', 'info');
  };
  recognition.onresult = event => {
    let finalText = '';
    let interimText = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
      else interimText += event.results[i][0].transcript;
    }
    if (finalText) {
      input.value = `${input.value}${input.value ? ' ' : ''}${finalText}`.trim();
      input.dispatchEvent(new Event('input'));
      showStatus('Voice captured. Review your message, then press Send.', 'success');
    } else if (interimText) {
      showStatus(`Hearing: ${interimText}`, 'info');
    }
  };
  recognition.onerror = event => {
    const messages = {
      'not-allowed': 'Microphone permission was denied. Allow microphone access in your browser.',
      'no-speech': 'I didn’t hear anything. Tap Voice and try again.',
      'network': 'Speech recognition needs an internet connection. Try again when connected.'
    };
    showStatus(messages[event.error] || 'Voice input stopped. Please try again.', 'error');
  };
  recognition.onend = () => {
    listening = false;
    record.classList.remove('recording');
    record.innerHTML = '🎙<span>Voice</span>';
  };
}
record.addEventListener('click', () => {
  if (!recognition) {
    showStatus('Voice typing is not supported in this browser. Try Chrome on Android or use your keyboard microphone.', 'info');
    return;
  }
  try {
    if (listening) recognition.stop();
    else recognition.start();
  } catch (error) {
    showStatus('Voice input could not start. Please try again.', 'error');
  }
});
load();
