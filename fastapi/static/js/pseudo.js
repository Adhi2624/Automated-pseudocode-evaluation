let questions = [];
let currentQuestion = 0;
const pseudoCodeInput = document.getElementById('pseudoCodeInput');
const questionNumber = document.getElementById('questionNumber');
const questionText = document.getElementById('questionText');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const saveBtn = document.getElementById('saveBtn');
const submitBtn = document.getElementById('submitBtn');

const answers = {};
let userDetails = {};

function currentKey() {
  return String(questions[currentQuestion].id);
}

function updateQuestion() {
  questionNumber.textContent = `Question ${currentQuestion + 1} of ${questions.length}`;
  questionText.textContent = questions[currentQuestion].text;
  pseudoCodeInput.value = answers[currentKey()] || '';
  prevBtn.disabled = currentQuestion === 0;
  nextBtn.disabled = currentQuestion >= questions.length - 1;
  // Show submit button on the last question
  submitBtn.style.display = currentQuestion === questions.length - 1 ? 'block' : 'none';
}

function saveAnswer() {
  if (questions.length === 0) return;
  answers[currentKey()] = pseudoCodeInput.value;
}

function handleNextQuestion() {
  if (currentQuestion < questions.length - 1) {
    saveAnswer();
    currentQuestion += 1;
    updateQuestion();
  }
}

function handlePreviousQuestion() {
  if (currentQuestion > 0) {
    saveAnswer();
    currentQuestion -= 1;
    updateQuestion();
  }
}

function handleSaveAnswer() {
  saveAnswer();
}

function errorMessage(xhr) {
  const detail = xhr.responseJSON && xhr.responseJSON.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg).filter(Boolean).join('\n');
  }
  return '';
}

function handleSubmit() {
  saveAnswer();

  const register_no = localStorage.getItem('register_no');
  if (!register_no) {
    alert('Register number not found. Please fill in your details first.');
    window.location.href = '/details';
    return;
  }

  submitBtn.disabled = true;
  $.ajax({
    url: `/submit-answers/${encodeURIComponent(register_no)}`,
    type: 'PUT',
    contentType: 'application/json',
    data: JSON.stringify({ pseudoCodeAnswers: answers }),
    success: function () {
      window.location.href = '/thank';
    },
    error: function (xhr) {
      if (xhr.status === 404) {
        window.location.href = '/details';
        return;
      }
      submitBtn.disabled = false;
      alert('Error submitting answers! ' + errorMessage(xhr));
      console.error('Status:', xhr.status, 'Response:', xhr.responseText);
    },
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const register_no = localStorage.getItem('register_no');
  if (!register_no) {
    window.location.href = '/details';
    return;
  }

  const questionsReq = $.ajax({ url: '/api/questions', type: 'GET', dataType: 'json' });
  const userReq = $.ajax({
    url: `/get-user-details/${encodeURIComponent(register_no)}`,
    type: 'GET',
    dataType: 'json',
  });

  $.when(questionsReq, userReq).then(
    function (qResult, uResult) {
      questions = qResult[0];
      userDetails = uResult[0];
      if (!Array.isArray(questions) || questions.length === 0) {
        alert('No questions available.');
        return;
      }
      if (userDetails.pseudoCodeAnswers) {
        Object.keys(userDetails.pseudoCodeAnswers).forEach((k) => {
          answers[String(k)] = userDetails.pseudoCodeAnswers[k];
        });
      }
      updateQuestion();
    },
    function (xhr) {
      if (xhr && xhr.status === 404) {
        window.location.href = '/details';
        return;
      }
      alert('Error loading the page data! ' + (xhr ? errorMessage(xhr) : ''));
      console.error('Status:', xhr && xhr.status, 'Response:', xhr && xhr.responseText);
    }
  );
});
