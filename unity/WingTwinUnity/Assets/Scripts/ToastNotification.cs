using System;
using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public class ToastNotification : MonoBehaviour
{
    [Header("Durations")]
    [SerializeField] private float autoDismissTime = 12f;
    [SerializeField] private float fadeDuration = 0.3f;

    [Header("Type Colors")]
    [SerializeField] private Color infoColor = new Color(0.15f, 0.35f, 0.75f, 0.95f);
    [SerializeField] private Color warningColor = new Color(0.75f, 0.55f, 0.05f, 0.95f);
    [SerializeField] private Color errorColor = new Color(0.75f, 0.15f, 0.15f, 0.95f);

    private string notificationId;
    private Action<string> onDismiss;
    private CanvasGroup canvasGroup;

    private void Awake()
    {
        canvasGroup = GetComponent<CanvasGroup>();
        if (canvasGroup == null)
        {
            canvasGroup = gameObject.AddComponent<CanvasGroup>();
        }
    }

    public static ToastNotification Create(string id, string type, string title, string message,
        Transform parent, ToastNotification prefab, Action<string> dismissCallback)
    {
        ToastNotification toast;

        if (prefab != null)
        {
            toast = Instantiate(prefab, parent);
        }
        else
        {
            GameObject go = new GameObject("Toast", typeof(RectTransform), typeof(CanvasGroup));
            go.transform.SetParent(parent, false);
            toast = go.AddComponent<ToastNotification>();
            toast.BuildUI();
        }

        toast.notificationId = id;
        toast.onDismiss = dismissCallback;
        toast.SetContent(type, title, message);
        toast.StartCoroutine(toast.AutoDismissRoutine());
        return toast;
    }

    public void Dismiss()
    {
        StopAllCoroutines();
        StartCoroutine(FadeOutAndDestroy());
    }

    private IEnumerator AutoDismissRoutine()
    {
        yield return new WaitForSeconds(autoDismissTime);
        Dismiss();
    }

    private IEnumerator FadeOutAndDestroy()
    {
        float elapsed = 0f;
        float startAlpha = canvasGroup != null ? canvasGroup.alpha : 1f;

        while (elapsed < fadeDuration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / fadeDuration;
            if (canvasGroup != null)
                canvasGroup.alpha = Mathf.Lerp(startAlpha, 0f, t);
            yield return null;
        }

        onDismiss?.Invoke(notificationId);
        Destroy(gameObject);
    }

    private void BuildUI()
    {
        RectTransform rt = GetComponent<RectTransform>();
        rt.anchorMin = new Vector2(1, 1);
        rt.anchorMax = new Vector2(1, 1);
        rt.pivot = new Vector2(1, 1);
        rt.sizeDelta = new Vector2(600, 160);
        rt.anchoredPosition = Vector2.zero;

        GameObject bgObj = new GameObject("Background", typeof(RectTransform), typeof(Image));
        bgObj.transform.SetParent(transform, false);
        Image bg = bgObj.GetComponent<Image>();

        RectTransform bgRt = bgObj.GetComponent<RectTransform>();
        bgRt.anchorMin = Vector2.zero;
        bgRt.anchorMax = Vector2.one;
        bgRt.sizeDelta = Vector2.zero;
        bgRt.anchoredPosition = Vector2.zero;

        GameObject hgroupObj = new GameObject("Content", typeof(RectTransform), typeof(HorizontalLayoutGroup));
        hgroupObj.transform.SetParent(transform, false);
        HorizontalLayoutGroup hgroup = hgroupObj.GetComponent<HorizontalLayoutGroup>();
        hgroup.padding = new RectOffset(14, 14, 14, 14);
        hgroup.spacing = 12;
        hgroup.childAlignment = TextAnchor.MiddleLeft;

        RectTransform hgRt = hgroupObj.GetComponent<RectTransform>();
        hgRt.anchorMin = Vector2.zero;
        hgRt.anchorMax = Vector2.one;
        hgRt.sizeDelta = Vector2.zero;

        GameObject textGroupObj = new GameObject("TextGroup", typeof(RectTransform), typeof(VerticalLayoutGroup),
            typeof(ContentSizeFitter));
        textGroupObj.transform.SetParent(hgroupObj.transform, false);
        VerticalLayoutGroup vgroup = textGroupObj.GetComponent<VerticalLayoutGroup>();
        vgroup.spacing = 4;
        vgroup.childAlignment = TextAnchor.MiddleLeft;
        ContentSizeFitter csf = textGroupObj.GetComponent<ContentSizeFitter>();
        csf.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

        RectTransform tgRt = textGroupObj.GetComponent<RectTransform>();
        tgRt.sizeDelta = new Vector2(0, 0);

        GameObject titleObj = new GameObject("Title", typeof(RectTransform), typeof(TextMeshProUGUI));
        titleObj.transform.SetParent(textGroupObj.transform, false);
        TextMeshProUGUI titleText = titleObj.GetComponent<TextMeshProUGUI>();
        titleText.fontSize = 28;
        titleText.fontStyle = FontStyles.Bold;
        titleText.color = Color.white;

        GameObject msgObj = new GameObject("Message", typeof(RectTransform), typeof(TextMeshProUGUI));
        msgObj.transform.SetParent(textGroupObj.transform, false);
        TextMeshProUGUI msgText = msgObj.GetComponent<TextMeshProUGUI>();
        msgText.fontSize = 22;
        msgText.color = new Color(0.9f, 0.9f, 0.9f, 1f);

        GameObject closeObj = new GameObject("CloseButton", typeof(RectTransform), typeof(Image), typeof(Button));
        closeObj.transform.SetParent(hgroupObj.transform, false);
        Button closeBtn = closeObj.GetComponent<Button>();
        RectTransform closeRt = closeObj.GetComponent<RectTransform>();
        closeRt.sizeDelta = new Vector2(40, 40);

        GameObject xObj = new GameObject("X", typeof(RectTransform), typeof(TextMeshProUGUI));
        xObj.transform.SetParent(closeObj.transform, false);
        TextMeshProUGUI xText = xObj.GetComponent<TextMeshProUGUI>();
        xText.text = "X";
        xText.fontSize = 28;
        xText.alignment = TextAlignmentOptions.Center;
        xText.color = Color.white;

        RectTransform xRt = xObj.GetComponent<RectTransform>();
        xRt.anchorMin = Vector2.zero;
        xRt.anchorMax = Vector2.one;
        xRt.sizeDelta = Vector2.zero;

        closeBtn.targetGraphic = closeObj.GetComponent<Image>();
        closeBtn.onClick.AddListener(Dismiss);
        ColorBlock colors = closeBtn.colors;
        colors.normalColor = new Color(1, 1, 1, 0.15f);
        colors.highlightedColor = new Color(1, 1, 1, 0.3f);
        closeBtn.colors = colors;
    }

    private void SetContent(string type, string title, string message)
    {
        Image bg = GetComponentInChildren<Image>();
        if (bg != null)
        {
            bg.color = type switch
            {
                "error" => errorColor,
                "warning" => warningColor,
                _ => infoColor,
            };
            bg.raycastTarget = true;
        }

        TextMeshProUGUI[] texts = GetComponentsInChildren<TextMeshProUGUI>();
        foreach (var t in texts)
        {
            if (t.gameObject.name == "Title")
                t.text = title;
            else if (t.gameObject.name == "Message")
                t.text = message;
        }
    }
}
