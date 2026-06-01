using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UIElements;

public class ToastManager : MonoBehaviour
{
    [Header("UI Document")]
    [SerializeField] private UIDocument uiDocument;

    [Header("Durations")]
    [SerializeField] private float autoDismissTime = 12f;
    [SerializeField] private float fadeDuration = 0.3f;

    [Header("Type Colors")]
    [SerializeField] private Color infoColor = new Color(0.15f, 0.35f, 0.75f, 0.95f);
    [SerializeField] private Color warningColor = new Color(0.75f, 0.55f, 0.05f, 0.95f);
    [SerializeField] private Color errorColor = new Color(0.75f, 0.15f, 0.15f, 0.95f);

    private VisualElement notificationContainer;
    private readonly Dictionary<string, VisualElement> activeToasts = new();
    private readonly HashSet<string> shownNotificationIds = new();

    private void Awake()
    {
        if (uiDocument == null)
            uiDocument = GetComponent<UIDocument>();
        if (uiDocument != null)
            notificationContainer = uiDocument.rootVisualElement?.Q("notification-container");
    }

    public void Show(string id, string type, string title, string message, Action<string> onDismiss)
    {
        if (string.IsNullOrEmpty(id) || shownNotificationIds.Contains(id) || notificationContainer == null)
            return;

        shownNotificationIds.Add(id);

        Color bgColor = type switch
        {
            "error" => errorColor,
            "warning" => warningColor,
            _ => infoColor,
        };

        var toast = new VisualElement();
        toast.name = "toast-" + id;
        toast.AddToClassList("toast");
        toast.style.backgroundColor = bgColor;

        var titleLabel = new Label(title);
        titleLabel.AddToClassList("toast-title");

        var msgLabel = new Label(message);
        msgLabel.AddToClassList("toast-message");

        var closeBtn = new Button(() => { if (onDismiss != null) StartCoroutine(FadeOutToast(id, onDismiss)); });
        closeBtn.text = "X";
        closeBtn.AddToClassList("toast-close-btn");

        toast.Add(titleLabel);
        toast.Add(msgLabel);
        toast.Add(closeBtn);

        notificationContainer.Add(toast);
        activeToasts[id] = toast;

        StartCoroutine(AutoDismissRoutine(id, onDismiss));
    }

    private IEnumerator AutoDismissRoutine(string id, Action<string> onDismiss)
    {
        yield return new WaitForSeconds(autoDismissTime);
        StartCoroutine(FadeOutToast(id, onDismiss));
    }

    private IEnumerator FadeOutToast(string id, Action<string> onDismiss)
    {
        if (!activeToasts.TryGetValue(id, out var toast))
            yield break;

        float elapsed = 0f;
        float startOpacity = toast.style.opacity.value;

        while (elapsed < fadeDuration)
        {
            elapsed += Time.deltaTime;
            toast.style.opacity = Mathf.Lerp(startOpacity, 0f, elapsed / fadeDuration);
            yield return null;
        }

        notificationContainer.Remove(toast);
        activeToasts.Remove(id);
        onDismiss?.Invoke(id);
    }
}
