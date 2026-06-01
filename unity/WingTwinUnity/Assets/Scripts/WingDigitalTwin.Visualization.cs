using Newtonsoft.Json;
using System;
using System.Linq;
using UnityEngine;
using UnityEngine.UIElements;

public partial class WingDigitalTwin : MonoBehaviour
{
    void CreateStressBar()
    {
        Texture2D tex = MakeGradientTexture(stressGradient);
        if (stressBar != null)
        {
            stressBar.style.backgroundImage = new StyleBackground(Background.FromTexture2D(tex));
        }
    }

    Texture2D MakeGradientTexture(Gradient gradient)
    {
        Texture2D tex = new Texture2D(stressBarWidth, stressBarHeight);
        for (int y = 0; y < stressBarHeight; y++)
        {
            float t = y / (float)(stressBarHeight - 1);
            Color c = gradient.Evaluate(t);
            for (int x = 0; x < stressBarWidth; x++)
                tex.SetPixel(x, y, c);
        }
        tex.Apply();
        return tex;
    }

    void UpdateLegendValues()
    {
        if (stressLabels == null)
            return;

        int labelCount = stressLabels.Length;

        if (showDamageHeatmap)
        {
            for (int i = 0; i < labelCount; i++)
            {
                float t = 1f - (float)i / (labelCount - 1);
                float value = Mathf.Lerp(0f, 1f, t);
                string suffix = i == 0 ? " Max" : i == labelCount - 1 ? " Min" : "";
                if (stressLabels[i] != null)
                    stressLabels[i].text = $"{value:P0}{suffix}";
            }
        }
        else
        {
            for (int i = 0; i < labelCount; i++)
            {
                float t = 1f - (float)i / (labelCount - 1);
                float value = Mathf.Lerp(0f, yieldPointPa, t);
                string suffix = i == 0 ? " Max" : i == labelCount - 1 ? " Min" : "";
                if (stressLabels[i] != null)
                    stressLabels[i].text = $"{value:E3}{suffix}";
            }
        }
    }

    void UpdateWingVisualization(TwinState data)
    {
        if (wingRenderer == null || stressGradient == null) return;

        if (usePerVertexHeatmap && mesh != null)
        {
            if (showDamageHeatmap && nodeDamages.Length > 0)
                UpdateDamageHeatmap();
            else if (stressField.Length > 0)
                UpdateHeatmap();
        }
        else
        {
            float t = Mathf.Clamp01(currentDamage);
            Color stressColor = stressGradient.Evaluate(t);
            wingRenderer.material.color = stressColor;
        }

        if (deformationField.Length > 0)
            UpdateDeformation();

        if (currentState == "red")
        {
            wingRenderer.material.EnableKeyword("_EMISSION");
            wingRenderer.material.SetColor("_EmissionColor", redColor * 2f);
        }
        else
        {
            wingRenderer.material.DisableKeyword("_EMISSION");
            float em = Mathf.Lerp(0.3f, 0.0f, currentDamage);
            wingRenderer.material.SetColor("_EmissionColor", new Color(em, em, em));
        }

        UpdateLegendValues();
    }

    void UpdateDeformation()
    {
        if (mesh == null || deformationField.Length == 0) return;

        if (deformationField.Length != originalVertices.Length)
        {
            Debug.LogWarning($"Deformation field length ({deformationField.Length}) != vertex count ({originalVertices.Length})");
            return;
        }

        for (int i = 0; i < originalVertices.Length; i++)
        {
            float updatedY = originalVertices[i].y + deformationField[i] * scaling;
            deformedVertices[i] = new Vector3(originalVertices[i].x,
                updatedY,
                originalVertices[i].z
                );
        }

        mesh.vertices = deformedVertices;
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();
    }

    void UpdateHeatmap()
    {
        if (mesh == null || stressField.Length == 0) return;

        int vertexCount = mesh.vertexCount;
        if (stressField.Length != vertexCount)
        {
            Debug.LogWarning($"Stress field length ({stressField.Length}) != vertex count ({vertexCount})");
            return;
        }

        if (vertexColors == null || vertexColors.Length != vertexCount)
            vertexColors = new Color[vertexCount];

        for (int i = 0; i < vertexCount; i++)
        {
            float absStress = Mathf.Abs(stressField[i]);
            float t = Mathf.Clamp01(absStress / yieldPointPa);
            vertexColors[i] = stressGradient.Evaluate(t);
        }

        mesh.colors = vertexColors;
        mesh.MarkDynamic();
    }

    void UpdateDamageHeatmap()
    {
        if (mesh == null || nodeDamages.Length == 0) return;

        int vertexCount = mesh.vertexCount;
        if (nodeDamages.Length != vertexCount)
        {
            Debug.LogWarning($"Node damages length ({nodeDamages.Length}) != vertex count ({vertexCount})");
            return;
        }

        if (vertexColors == null || vertexColors.Length != vertexCount)
            vertexColors = new Color[vertexCount];

        for (int i = 0; i < vertexCount; i++)
        {
            float t = Mathf.Clamp01(nodeDamages[i]);
            vertexColors[i] = stressGradient.Evaluate(t);
        }

        mesh.colors = vertexColors;
        mesh.MarkDynamic();
    }

    public void LoadMeshFromJson(string jsonPath)
    {
        if (!System.IO.File.Exists(jsonPath))
        {
            Debug.LogError($"Mesh file not found: {jsonPath}");
            return;
        }

        string json = System.IO.File.ReadAllText(jsonPath);
        MeshData data = JsonConvert.DeserializeObject<MeshData>(json);

        if (data?.vertices == null || data?.triangles == null)
        {
            Debug.LogError("Failed to load mesh: parsed data is null.");
            return;
        }

        mesh = new Mesh();
        mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;

        originalVertices = data.vertices.Select(v => new Vector3(v[0], v[1], v[2])).ToArray();
        mesh.vertices = originalVertices;

        deformedVertices = new Vector3[originalVertices.Length];

        int[] triangles = data.triangles.SelectMany(t => t).ToArray();
        mesh.triangles = triangles;

        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

        wingRenderer.GetComponent<MeshFilter>().mesh = mesh;
        meshStressValues = new float[originalVertices.Length];

        Debug.Log($"Loaded mesh: {originalVertices.Length} vertices, {triangles.Length / 3} triangles");
    }

    [Serializable]
    public class MeshData
    {
        public System.Collections.Generic.List<System.Collections.Generic.List<float>> vertices;
        public System.Collections.Generic.List<System.Collections.Generic.List<int>> triangles;
    }
}
