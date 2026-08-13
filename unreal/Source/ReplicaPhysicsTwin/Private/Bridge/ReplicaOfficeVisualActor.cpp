#include "Bridge/ReplicaOfficeVisualActor.h"

#include "Bridge/ReplicaMeshFormat.h"
#include "ProceduralMeshComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"

AReplicaOfficeVisualActor::AReplicaOfficeVisualActor()
{
	PrimaryActorTick.bCanEverTick = false;

	VisualMesh = CreateDefaultSubobject<UProceduralMeshComponent>(TEXT("ReplicaOfficeVisualMesh"));
	RootComponent = VisualMesh;
	VisualMesh->SetMobility(EComponentMobility::Static);
	VisualMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	VisualMesh->SetCastShadow(true);
}

void AReplicaOfficeVisualActor::BeginPlay()
{
	Super::BeginPlay();

	const FString AbsolutePath = FPaths::IsRelative(SourceMeshPath)
		? FPaths::ConvertRelativePathToFull(FPaths::ProjectDir(), SourceMeshPath)
		: FPaths::ConvertRelativePathToFull(SourceMeshPath);
	bMeshLoaded = LoadDerivedMesh(AbsolutePath);
	if (!bMeshLoaded)
	{
		UE_LOG(LogTemp, Warning, TEXT("Replica office_0 visual mesh was not loaded: %s"), *AbsolutePath);
	}
}

bool AReplicaOfficeVisualActor::LoadDerivedMesh(const FString& AbsolutePath)
{
	TArray<uint8> Bytes;
	if (!FFileHelper::LoadFileToArray(Bytes, *AbsolutePath))
	{
		return false;
	}

	constexpr int32 HeaderBytes = 16;
	if (Bytes.Num() >= 8 && FMemory::Memcmp(Bytes.GetData(), "RPTMESH2", 8) == 0)
	{
		// ReplicaCAD RPTMESH2 carries per-vertex colors; the shared loader keeps
		// those colors instead of repainting the whole scene gray.
		return ReplicaMeshFormat::LoadRPTMesh2(VisualMesh, Bytes, AbsolutePath, FLinearColor::White);
	}
	if (Bytes.Num() < HeaderBytes || FMemory::Memcmp(Bytes.GetData(), "RPTMESH1", 8) != 0)
	{
		UE_LOG(LogTemp, Error, TEXT("Invalid Replica visual mesh header: %s"), *AbsolutePath);
		return false;
	}

	uint32 VertexCount = 0;
	uint32 IndexCount = 0;
	FMemory::Memcpy(&VertexCount, Bytes.GetData() + 8, sizeof(uint32));
	FMemory::Memcpy(&IndexCount, Bytes.GetData() + 12, sizeof(uint32));
	if (VertexCount == 0 || IndexCount == 0 || (IndexCount % 3) != 0)
	{
		UE_LOG(LogTemp, Error, TEXT("Invalid Replica visual mesh counts: vertices=%u indices=%u"), VertexCount, IndexCount);
		return false;
	}

	const uint64 ExpectedBytes = static_cast<uint64>(HeaderBytes)
		+ static_cast<uint64>(VertexCount) * sizeof(float) * 3 * 2
		+ static_cast<uint64>(IndexCount) * sizeof(uint32);
	if (ExpectedBytes != static_cast<uint64>(Bytes.Num()))
	{
		UE_LOG(LogTemp, Error, TEXT("Replica visual mesh size mismatch: expected=%llu actual=%d"), ExpectedBytes, Bytes.Num());
		return false;
	}

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<int32> Triangles;
	Vertices.SetNumUninitialized(static_cast<int32>(VertexCount));
	Normals.SetNumUninitialized(static_cast<int32>(VertexCount));
	Triangles.SetNumUninitialized(static_cast<int32>(IndexCount));

	const uint8* Cursor = Bytes.GetData() + HeaderBytes;
	for (uint32 Index = 0; Index < VertexCount; ++Index)
	{
		float Values[3];
		FMemory::Memcpy(Values, Cursor, sizeof(Values));
		Cursor += sizeof(Values);
		Vertices[static_cast<int32>(Index)] = FVector(Values[0], Values[1], Values[2]);
	}
	for (uint32 Index = 0; Index < VertexCount; ++Index)
	{
		float Values[3];
		FMemory::Memcpy(Values, Cursor, sizeof(Values));
		Cursor += sizeof(Values);
		Normals[static_cast<int32>(Index)] = FVector(Values[0], Values[1], Values[2]);
	}
	for (uint32 Index = 0; Index < IndexCount; ++Index)
	{
		uint32 VertexIndex = 0;
		FMemory::Memcpy(&VertexIndex, Cursor, sizeof(uint32));
		Cursor += sizeof(uint32);
		if (VertexIndex >= VertexCount)
		{
			UE_LOG(LogTemp, Error, TEXT("Replica visual mesh index out of range: %u >= %u"), VertexIndex, VertexCount);
			return false;
		}
		Triangles[static_cast<int32>(Index)] = static_cast<int32>(VertexIndex);
	}

	struct FPaletteSection
	{
		TArray<FVector> SectionVertices;
		TArray<FVector> SectionNormals;
		TArray<int32> SectionTriangles;
		TArray<FColor> SectionColors;
		TArray<int32> Remap;
	};

	// The source scene has no usable runtime texture/material binding.  Split
	// the room into lighting/material groups so the scene reads as a real
	// interior instead of one unlit gray surface.
	const TArray<FLinearColor> Palette = {
		FLinearColor(0.26f, 0.22f, 0.16f, 1.0f), // floor/rug
		FLinearColor(0.56f, 0.34f, 0.16f, 1.0f), // wood/table tops
		FLinearColor(0.70f, 0.59f, 0.46f, 1.0f), // warm walls/furniture sides
		FLinearColor(0.12f, 0.11f, 0.10f, 1.0f), // undersides/shadows
	};
	TArray<FPaletteSection> Sections;
	Sections.SetNum(Palette.Num());
	for (FPaletteSection& Section : Sections)
	{
		Section.Remap.Init(INDEX_NONE, Vertices.Num());
	}

	for (int32 TriangleIndex = 0; TriangleIndex + 2 < Triangles.Num(); TriangleIndex += 3)
	{
		const int32 SourceA = Triangles[TriangleIndex];
		const int32 SourceB = Triangles[TriangleIndex + 1];
		const int32 SourceC = Triangles[TriangleIndex + 2];
		const FVector& A = Vertices[SourceA];
		const FVector& B = Vertices[SourceB];
		const FVector& C = Vertices[SourceC];
		const FVector FaceNormal = FVector::CrossProduct(B - A, C - A);
		if (FaceNormal.SizeSquared() <= KINDA_SMALL_NUMBER)
		{
			continue;
		}

	// The exported Replica room faces are already wound toward the room
	// interior.  Keep that winding and its normal direction; inverting it here
	// makes the floor and walls face away from the interior lights and renders
	// most of the room nearly black.
	const FVector SurfaceNormal = FaceNormal;
	const FVector UnitNormal = SurfaceNormal.GetSafeNormal();
		const FVector Center = (A + B + C) / 3.0f;
		int32 PaletteIndex = 2;
		if (Center.Z <= 14.0f)
		{
			PaletteIndex = 0;
		}
		else if (UnitNormal.Z > 0.60f)
		{
			PaletteIndex = 1;
		}
		else if (UnitNormal.Z < -0.60f)
		{
			PaletteIndex = 3;
		}

		FPaletteSection& Section = Sections[PaletteIndex];
		const int32 SourceIndices[3] = {SourceA, SourceB, SourceC};
		for (const int32 SourceIndex : SourceIndices)
		{
			int32& SectionIndex = Section.Remap[SourceIndex];
			if (SectionIndex == INDEX_NONE)
			{
				SectionIndex = Section.SectionVertices.Num();
				Section.SectionVertices.Add(Vertices[SourceIndex]);
				Section.SectionNormals.Add(FVector::ZeroVector);
			}
			Section.SectionTriangles.Add(SectionIndex);
			Section.SectionNormals[SectionIndex] += SurfaceNormal;
		}
	}

	VisualMesh->ClearAllMeshSections();
	UMaterialInterface* VertexColorMaterial = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/EngineDebugMaterials/VertexColorMaterial.VertexColorMaterial"));
	UMaterialInterface* BaseMaterial = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
	for (int32 SectionIndex = 0; SectionIndex < Sections.Num(); ++SectionIndex)
	{
		FPaletteSection& Section = Sections[SectionIndex];
		if (Section.SectionTriangles.Num() == 0)
		{
			continue;
		}
		for (FVector& Normal : Section.SectionNormals)
		{
			Normal = Normal.IsNearlyZero() ? FVector::UpVector : Normal.GetSafeNormal();
		}
		Section.SectionColors.Init(Palette[SectionIndex].ToFColor(true), Section.SectionVertices.Num());
		TArray<FVector2D> UV0;
		TArray<FProcMeshTangent> Tangents;
		VisualMesh->CreateMeshSection(
			SectionIndex,
			Section.SectionVertices,
			Section.SectionTriangles,
			Section.SectionNormals,
			UV0,
			Section.SectionColors,
			Tangents,
			false);

		// This mesh carries its scene palette in vertex colors.  Prefer the
		// engine vertex-color material because it remains visible in standalone
		// even when no baked lighting/material instance is available.
		if (VertexColorMaterial != nullptr)
		{
			VisualMesh->SetMaterial(SectionIndex, VertexColorMaterial);
		}
		else if (BaseMaterial != nullptr)
		{
			if (UMaterialInstanceDynamic* DynamicMaterial = UMaterialInstanceDynamic::Create(BaseMaterial, this))
			{
				DynamicMaterial->SetVectorParameterValue(TEXT("Color"), Palette[SectionIndex]);
				DynamicMaterial->SetScalarParameterValue(TEXT("Roughness"), 0.82f);
				VisualMesh->SetMaterial(SectionIndex, DynamicMaterial);
			}
		}
	}
	if (BaseMaterial == nullptr && VertexColorMaterial == nullptr)
	{
		UE_LOG(LogTemp, Warning, TEXT("Replica visual palette materials could not be loaded"));
	}
	VisualMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	UE_LOG(LogTemp, Log, TEXT("Loaded Replica office_0 visual mesh: %s vertices=%u triangles=%u"),
		*AbsolutePath, VertexCount, IndexCount / 3);
	return true;
}
