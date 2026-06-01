using UnityEngine;

public partial class WingDigitalTwin : MonoBehaviour
{
    private GameObject view3Axes;
    private GameObject axisYObj;
    private GameObject axisZObj;

    void CreateAxes()
    {
        view3Axes = new GameObject("View3Axes");
        Transform parent = planeScene != null ? planeScene.transform : null;
        if (parent != null)
            view3Axes.transform.SetParent(parent);
        view3Axes.transform.localPosition = Vector3.zero;
        view3Axes.transform.localRotation = Quaternion.identity;
        view3Axes.transform.localScale = Vector3.one;
        view3Axes.SetActive(false);

        float length = 100f;
        float thickness = 0.3f;

        axisYObj = CreateAxisBar(view3Axes.transform, "AxisY", Vector3.up, length, thickness, Color.red);
        axisZObj = CreateAxisBar(view3Axes.transform, "AxisZ", Vector3.forward, length, thickness, Color.red);
    }

    GameObject CreateAxisBar(Transform parent, string name, Vector3 dir, float length, float thickness, Color color)
    {
        GameObject go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = name;
        go.transform.SetParent(parent);
        go.transform.localPosition = Vector3.zero;
        go.transform.localRotation = Quaternion.FromToRotation(Vector3.up, dir);
        go.transform.localScale = new Vector3(thickness, length * 2, thickness);

        UnityEngine.Object.Destroy(go.GetComponent<BoxCollider>());

        Shader shader = Shader.Find("Unlit/Color");
        if (shader == null) shader = Shader.Find("Sprites/Default");
        if (shader != null)
        {
            Material mat = new Material(shader);
            mat.color = color;
            go.GetComponent<MeshRenderer>().material = mat;
        }
        return go;
    }
}
