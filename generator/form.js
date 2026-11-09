(function () {
  var form = document.getElementById("apply-form");
  var status = document.getElementById("form-status");
  var button = form.querySelector("button[type=submit]");
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  var PHONE = /^[0-9０-９+＋()（）\sー－-]{10,}$/;

  function show(message, kind, withPhoneLink) {
    status.hidden = false;
    status.className = "form-status is-" + kind;
    status.textContent = message;
    if (withPhoneLink) {
      var link = document.createElement("a");
      link.className = "btn btn-tel btn-wide";
      link.href = "tel:" + form.dataset.phone;
      link.textContent = "電話する";
      status.appendChild(link);
    }
    status.scrollIntoView({ block: "center" });
  }

  function askToCall() {
    show(form.dataset.phoneMessage, "error", true);
  }

  function validate(data) {
    var contact = (data.get("contact") || "").trim();
    if (!(data.get("name") || "").trim()) return "お名前を入力してください。";
    if (!EMAIL.test(contact) && !PHONE.test(contact)) return "電話番号またはメールアドレスを入力してください。";
    if (!data.get("contact_method")) return "希望する連絡方法を選んでください。";
    if (data.get("contact_method") === "メール" && !EMAIL.test(contact)) return "メールでの連絡をご希望の場合は、メールアドレスを入力してください。";
    if (data.get("contact_method") === "電話" && !PHONE.test(contact)) return "電話での連絡をご希望の場合は、電話番号を入力してください。";
    if (!data.get("adult")) return "18歳以上であることをご確認ください。";
    if (!data.get("privacy")) return "個人情報の取り扱いへの同意をお願いします。";
    return "";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var endpoint = typeof APPLY_ENDPOINT === "string" ? APPLY_ENDPOINT : "";
    if (!endpoint) {
      askToCall();
      return;
    }
    var data = new FormData(form);
    var problem = validate(data);
    if (problem) {
      show(problem, "error", false);
      return;
    }
    button.disabled = true;
    fetch(endpoint, { method: "POST", body: data })
      .then(function (response) {
        if (!response.ok) throw new Error(String(response.status));
        form.reset();
        show("お申し込みを受け付けました。ご希望の連絡方法でご連絡します。", "ok", false);
      })
      .catch(askToCall)
      .finally(function () {
        button.disabled = false;
      });
  });

  button.disabled = false;
})();
