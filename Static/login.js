document.getElementById("login-form").addEventListener("submit", function (e) {
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value.trim();
    const errorMsg = document.getElementById("error-msg");
  
    if (!email || !password) {
      e.preventDefault();
      errorMsg.style.display = "block";
    } else {
      errorMsg.style.display = "none";
    }
  });
  